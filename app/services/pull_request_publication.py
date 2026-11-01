import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from urllib.parse import quote, urlsplit

from app.core.errors import CodeHostError, PlacementError, PublicationUncertainError
from app.models.github import HostComment, Placement
from app.provider.github.abstract import CodeHostAbstract, CommentKind
from app.schemas.code_change import ChangeScope
from app.schemas.github import ReviewJob
from app.schemas.local_review import ReviewOutcome
from app.schemas.review import Finding, Limitation, ReviewRecord
from app.services.ports import PublicationRepository
from app.services.review_report import ReviewReportService

SUMMARY_MARKER = "<!-- rush:summary -->"
FINDING = re.compile(r"<!-- rush:finding:([0-9a-f]{64}):(\d+) -->")
RESOLVED = "<!-- rush:resolved -->"
REASSESSMENT = "<!-- rush:reassessment -->"
HISTORY = "<!-- rush:history -->"
REOPENED = "<!-- rush:reopened -->"
SUMMARY_LIMIT = 60000
NOT_RUN = "_No application code or tests were run. This review is advisory._"
CATEGORIES = (
    (
        "Missing context",
        frozenset(
            {
                "missing_ticket",
                "missing_context",
                "access_denied",
                "rate_limited",
                "content_truncated",
                "conflicting_sources",
                "unresolved_question",
                "required_skill_unsupported",
                "scope_excluded",
            }
        ),
    ),
    ("Exhausted limits", frozenset({"budget"})),
    (
        "Policy problems",
        frozenset({"policy_conflict", "guideline_changed", "policy_not_applied"}),
    ),
)
Conclusion = Literal["success", "neutral", "failure"]


@dataclass
class Publication:
    inline: list[Finding] = field(default_factory=list)
    in_summary: list[Finding] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    resolved: int = 0
    unchecked: int = 0
    links: dict[str, str] = field(default_factory=dict)


# GitHub treats any non-ASCII-word character before "@" as a mention boundary.
MENTION = re.compile(r"(?<![A-Za-z0-9_])@(?=[A-Za-z0-9])", re.ASCII)


def safe_text(text: str) -> str:
    # Model text must not hide content, mention people or load images.
    text = MENTION.sub("@\u200b", text.replace("<", "&lt;"))
    return text.replace("![", "!\\[")


def _identities(findings: tuple[Finding, ...]) -> list[tuple[str, Finding]]:
    counts: dict[str, int] = {}
    named = []
    for finding in findings:
        counts[finding.fingerprint] = counts.get(finding.fingerprint, 0) + 1
        named.append((f"{finding.fingerprint}:{counts[finding.fingerprint]}", finding))
    return named


def where(finding: Finding) -> str:
    anchor = finding.anchor
    side = "new" if anchor.side == "RIGHT" else "old"
    return f"`{anchor.path}` line {anchor.line} ({side} version)"


def resolved(body: str) -> bool:
    return body.rfind(RESOLVED) > body.rfind(REOPENED)


def _history(body: str, previous: str, head: str) -> str:
    original, separator, reassessment = previous.partition(REASSESSMENT)
    if RESOLVED in reassessment:
        reassessment, _, resolution = reassessment.partition(RESOLVED)
        original += "\n\n" + RESOLVED + resolution
    position = original.find(HISTORY)
    if position < 0:
        position = original.find(RESOLVED)
    if position >= 0:
        history = original[position:]
        if not history.startswith(HISTORY):
            history = HISTORY + "\n" + history
        body += "\n\n" + history
    if resolved(previous):
        body += f"\n\n{REOPENED}\n**Reopened:** reported again at `{head[:12]}`."
    if separator:
        body += "\n\n" + REASSESSMENT + reassessment
    return body


def _group(
    limitations: tuple[Limitation, ...], no_rules: bool = False
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for item in limitations:
        name = next(
            (title for title, codes in CATEGORIES if item.code in codes),
            "Other limitations",
        )
        reason = item.reason.split("; not fully reviewed:", 1)[0]
        if (
            no_rules
            and item.code == "policy_not_applied"
            and reason.lower().startswith("no approved")
        ):
            reason = "No approved team rule applies to these files."
        for code, plain in (
            ("source_bytes", "source allowance"),
            ("context_bytes", "ticket and policy allowance"),
            ("changed_files", "file allowance"),
            ("changed_lines", "changed-line allowance"),
            ("model_calls", "model-call allowance"),
            ("wall_seconds", "review time"),
        ):
            reason = reason.replace(code, plain)
        reason = safe_text(reason)
        if reason not in groups.setdefault(name, []):
            groups[name].append(reason)
    return groups


def _finding_line(finding: Finding, url: str, wording: str | None = None) -> str:
    label = safe_text(f"{finding.anchor.path}:{finding.anchor.line}")
    label = label.replace("[", "\\[").replace("]", "\\]")
    parsed = urlsplit(url)
    link = (
        f"[{label}]({quote(url, safe='/:#?=&%')})"
        if parsed.scheme == "https" and parsed.hostname and not parsed.username
        else label
    )
    problem = re.split(
        r"(?<=[.!?])\s+", " ".join((wording or finding.problem).split()), maxsplit=1
    )[0]
    return f"- **{finding.severity.title()} {finding.category}** {link}: " + safe_text(
        problem[:240]
    )


class PullRequestPublisher:
    """
    Keep one summary, one inline comment per lasting finding and one advisory
    check on the PR. Existing comments are edited, never deleted, so replies stay.
    """

    def __init__(
        self,
        host: CodeHostAbstract,
        store: PublicationRepository,
        clock: Callable[[], datetime],
    ) -> None:
        self._host, self._store, self._clock = host, store, clock

    async def publish(self, job: ReviewJob, outcome: ReviewOutcome) -> str | None:
        """
        Publish the outcome; return None if a newer commit arrived meanwhile.
        """
        record = outcome.record
        earlier: dict[str, HostComment] = {}
        for comment in await self._comments(job, "review"):
            if match := FINDING.match(comment.body):
                earlier[f"{match[1]}:{match[2]}"] = comment
        publication = Publication()
        for identity, finding in _identities(record.progress.result.findings):
            if not await self._current(job, record.inputs.head_sha):
                return None
            await self._finding(
                job,
                record,
                identity,
                finding,
                earlier.pop(identity, None),
                publication,
                outcome.investigation.scope,
            )
        if not await self._current(job, record.inputs.head_sha):
            return None
        excluded = (
            frozenset(
                item.new_path or item.old_path
                for item in outcome.investigation.scope.omissions
            )
            if outcome.investigation.scope
            else frozenset()
        )
        await self._resolve(job, record, earlier, publication, excluded)
        if publication.inline:
            for comment in await self._comments(job, "review"):
                if match := FINDING.match(comment.body):
                    publication.links[f"{match[1]}:{match[2]}"] = comment.html_url
        conclusion, title = self.conclusion(record, publication)
        summary = self.summary(outcome, title, publication)
        if not await self._current(job, record.inputs.head_sha):
            return None
        await self._summary(job, record.id, summary)
        await self._host.report_check(
            job.installation_id,
            job.repository,
            record.inputs.head_sha,
            conclusion,
            title,
            summary,
        )
        return title

    async def failure(
        self, job: ReviewJob, run_id: str, head_sha: str, reason: str
    ) -> None:
        summary = "\n".join(
            [
                SUMMARY_MARKER,
                "## rush review: could not run",
                "",
                f"Commit `{head_sha[:12]}`. Execution error: {reason}",
                "",
                NOT_RUN,
            ]
        )
        try:
            await self._summary(job, run_id, summary)
            await self._host.report_check(
                job.installation_id,
                job.repository,
                head_sha,
                "failure",
                "Review could not run",
                summary,
            )
        except CodeHostError:
            return

    @staticmethod
    def conclusion(
        record: ReviewRecord, publication: Publication
    ) -> tuple[Conclusion, str]:
        reason = record.progress.events[-1].reason
        if record.status == "failed":
            return "failure", f"Review could not run: {reason}"
        if record.status == "skipped":
            return "neutral", f"Not reviewed: {reason}"
        findings = len(record.progress.result.findings)
        incomplete = record.status != "completed"
        if findings:
            title = f"{findings} finding{'s' if findings != 1 else ''}"
            title += "; review incomplete" if incomplete else ""
        elif incomplete:
            title = "Review incomplete; no findings so far"
        else:
            title = "No supported problems found"
        if publication.problems:
            title += "; some results could not be published"
        if publication.unchecked and not incomplete:
            title += "; earlier findings not rechecked"
        passed = not (
            findings or incomplete or publication.problems or publication.unchecked
        )
        return ("success" if passed else "neutral"), title

    def summary(
        self, outcome: ReviewOutcome, title: str, publication: Publication
    ) -> str:
        record = outcome.record
        inputs = record.inputs
        findings = record.progress.result.findings
        headline = title if findings else f"0 findings; {title[:1].lower() + title[1:]}"
        lines = [
            SUMMARY_MARKER,
            f"## rush review: {headline}",
            "",
            f"Reviewed `{inputs.head_sha[:12]}` from `{inputs.merge_base_sha[:12]}`"
            f" (run `{record.id}`).",
            "",
            *((outcome.withheld, "") if outcome.withheld else ()),
        ]
        if findings:
            presentations = {
                item.finding_id: item.wording.problem
                for item in record.progress.result.presentations
            }
            lines += [
                _finding_line(
                    finding,
                    publication.links.get(identity, ""),
                    presentations.get(finding.id),
                )
                for identity, finding in _identities(findings)
            ]
            lines.append("")
        if not inputs.rules:
            lines += ["No approved team rule applies to these files.", ""]
        details = (
            [
                "**Comment wording**",
                "",
                *(
                    f"- {safe_text(note)}"
                    for note in record.progress.result.presentation_notes
                ),
                "",
            ]
            if record.progress.result.presentation_notes
            else []
        )
        for name, reasons in _group(
            record.progress.result.limitations, not inputs.rules
        ).items():
            details += [f"**{name}**", "", *(f"- {text}" for text in reasons), ""]
        if record.status == "failed":
            details += [
                "Execution error: " + safe_text(record.progress.events[-1].reason),
                "",
            ]
        if publication.problems:
            details += ["**Publication problems**", ""]
            details += [
                f"- {safe_text(text)}" for text in dict.fromkeys(publication.problems)
            ] + [""]
        if details:
            lines += [
                "<details>",
                "<summary>Review limitations</summary>",
                "",
                *details,
                "</details>",
                "",
            ]
        skipped = self._skipped(outcome)
        if skipped:
            lines += [
                "<details>",
                f"<summary>Ignored or skipped files ({len(skipped)})</summary>",
                "",
                *skipped,
                "",
                "</details>",
                "",
            ]
        if publication.resolved or publication.unchecked:
            lines += [
                f"Earlier findings: {publication.resolved} resolved after a recheck; "
                f"{publication.unchecked} not rechecked within "
                "this run's reviewed scope.",
                "",
            ]
        text = "\n".join(lines)
        if len(text) > SUMMARY_LIMIT:
            text = (
                text[:SUMMARY_LIMIT]
                + "\n\n_The rest was cut to fit GitHub's comment limit; see `rush "
                "jobs` and the review record._"
            )
        return f"{text}\n\n{NOT_RUN}"

    @staticmethod
    def _skipped(outcome: ReviewOutcome) -> list[str]:
        files = {}
        if scope := outcome.investigation.scope:
            for item in scope.omissions:
                files[item.new_path or item.old_path] = (
                    "intentionally ignored" if item.intentional else item.detail
                )
        for batch in outcome.record.progress.result.batches:
            if batch.status != "completed":
                for path in batch.paths:
                    files.setdefault(
                        path, "not fully reviewed before the review stopped"
                    )
        return [
            f"- {safe_text(path or 'unnamed file')}: {safe_text(reason)}"
            for path, reason in files.items()
        ]

    @staticmethod
    def _placement(
        record: ReviewRecord, finding: Finding, scope: ChangeScope | None
    ) -> Placement:
        anchor = finding.anchor
        start, end = anchor.line, anchor.line
        for file in scope.files if scope else ():
            for hunk in file.hunks:
                if hunk.id != anchor.hunk_id:
                    continue
                for evidence in finding.evidence:
                    if evidence.source_id != f"diff:{hunk.id}":
                        continue
                    lines = hunk.lines[evidence.start - 1 : evidence.end]
                    kind = "added" if anchor.side == "RIGHT" else "removed"
                    numbers = [
                        line.new_line if anchor.side == "RIGHT" else line.old_line
                        for line in lines
                        if line.kind == kind
                    ]
                    if numbers and all(n is not None for n in numbers):
                        actual = [n for n in numbers if n is not None]
                        if anchor.line in actual and max(actual) - min(
                            actual
                        ) + 1 == len(actual):
                            start, end = min(actual), max(actual)
        return Placement(
            record.inputs.head_sha,
            anchor.path,
            end,
            anchor.side,
            start if start != end else None,
        )

    async def _finding(
        self,
        job: ReviewJob,
        record: ReviewRecord,
        identity: str,
        finding: Finding,
        comment: HostComment | None,
        publication: Publication,
        scope: ChangeScope | None,
    ) -> None:
        item, marker = f"finding:{identity}", f"<!-- rush:finding:{identity} -->"
        presentation = next(
            (
                item
                for item in record.progress.result.presentations
                if item.finding_id == finding.id
            ),
            None,
        )
        text = [
            safe_text(line)
            for line in ReviewReportService.finding_text(finding, presentation)
        ]
        if presentation is not None and presentation.settings.verbosity == "short":
            text = [
                *text[:5],
                text[7],
                "",
                "<details>",
                "<summary>Example and evidence</summary>",
                "",
                *text[5:7],
                *text[8:],
                "</details>",
            ]
        body = "\n".join([marker, *text])
        await self._store.plan(record.id, item, "review", self._clock())
        try:
            if comment is not None:
                body = _history(body, comment.body, record.inputs.head_sha)
                await self._edit(job, "review", comment.id, body)
                comment_id = comment.id
            else:
                placement = self._placement(record, finding, scope)
                comment_id = await self._create(job, body, marker, placement)
        except PlacementError as error:
            publication.in_summary.append(finding)
            publication.problems.append(f"{where(finding)}: {error}")
            await self._settle(record.id, item, "in_summary", None, None)
            return
        except CodeHostError as error:
            publication.in_summary.append(finding)
            publication.problems.append(f"{where(finding)}: {error}")
            await self._settle(record.id, item, "failed", None, str(error))
            return
        publication.inline.append(finding)
        await self._settle(record.id, item, "published", comment_id, None)

    async def _resolve(
        self,
        job: ReviewJob,
        record: ReviewRecord,
        earlier: dict[str, HostComment],
        publication: Publication,
        excluded: frozenset[str | None] = frozenset(),
    ) -> None:
        for comment in earlier.values():
            if resolved(comment.body):
                continue
            if record.status != "completed" or (
                comment.path is not None and comment.path in excluded
            ):
                publication.unchecked += 1
                continue
            if not await self._current(job, record.inputs.head_sha):
                return
            note = (
                f"{RESOLVED}\n**Resolved:** rush rechecked "
                f"`{record.inputs.head_sha[:12]}` and no longer reports this finding "
                "(it was fixed, waived by an approved exception, or withdrawn)."
            )
            try:
                original, separator, reassessment = comment.body.partition(REASSESSMENT)
                if HISTORY not in original:
                    original += "\n\n" + HISTORY
                body = f"{original}\n\n{note}"
                if separator:
                    body += "\n\n" + REASSESSMENT + reassessment
                await self._edit(job, "review", comment.id, body)
            except CodeHostError as error:
                publication.problems.append(f"An earlier finding stayed open: {error}")
                continue
            publication.resolved += 1

    async def _summary(self, job: ReviewJob, run_id: str, body: str) -> None:
        await self._store.plan(run_id, "summary", "issue", self._clock())
        try:
            existing = [
                comment
                for comment in await self._comments(job, "issue")
                if SUMMARY_MARKER in comment.body
            ]
            if existing:
                await self._edit(job, "issue", existing[0].id, body)
                comment_id = existing[0].id
            else:
                comment_id = await self._create(job, body, SUMMARY_MARKER, None)
        except CodeHostError as error:
            await self._settle(run_id, "summary", "failed", None, str(error))
            raise
        await self._settle(run_id, "summary", "published", comment_id, None)

    async def _create(
        self, job: ReviewJob, body: str, marker: str, placement: Placement | None
    ) -> int:
        post = (job.installation_id, job.repository, job.pull_request, body, placement)
        try:
            return await self._host.post_comment(*post)
        except PublicationUncertainError:
            # The comment may have been saved; look before posting it again.
            kind: CommentKind = "issue" if placement is None else "review"
            for comment in await self._comments(job, kind):
                if marker in comment.body:
                    return comment.id
            return await self._host.post_comment(*post)

    async def _current(self, job: ReviewJob, head_sha: str) -> bool:
        pull = await self._host.pull_request(
            job.installation_id, job.repository, job.pull_request
        )
        return pull.head_sha == head_sha

    async def _comments(self, job: ReviewJob, kind: CommentKind) -> list[HostComment]:
        return await self._host.bot_comments(
            job.installation_id, job.repository, job.pull_request, kind
        )

    async def _edit(
        self, job: ReviewJob, kind: CommentKind, comment_id: int, body: str
    ) -> None:
        await self._host.edit_comment(
            job.installation_id, job.repository, kind, comment_id, body
        )

    async def _settle(
        self,
        run_id: str,
        item: str,
        status: str,
        comment_id: int | None,
        detail: str | None,
    ) -> None:
        await self._store.settle(
            run_id, item, status, comment_id, detail, self._clock()
        )
