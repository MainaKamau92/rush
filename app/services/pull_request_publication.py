import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.core.errors import CodeHostError, PlacementError, PublicationUncertainError
from app.models.github import HostComment, Placement
from app.provider.github.abstract import CodeHostAbstract, CommentKind
from app.schemas.github import ReviewJob
from app.schemas.local_review import ReviewOutcome
from app.schemas.review import Finding, Limitation, ReviewRecord
from app.services.ports import PublicationRepository
from app.services.review_report import ReviewReportService

SUMMARY_MARKER = "<!-- rush:summary -->"
FINDING = re.compile(r"<!-- rush:finding:([0-9a-f]{64}):(\d+) -->")
RESOLVED = "<!-- rush:resolved -->"
REASSESSMENT = "<!-- rush:reassessment -->"
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


def _group(limitations: tuple[Limitation, ...]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for item in limitations:
        name = next(
            (title for title, codes in CATEGORIES if item.code in codes),
            "Other limitations",
        )
        groups.setdefault(name, []).append(f"{safe_text(item.reason)} (`{item.code}`)")
    return groups


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
            await self._finding(
                job, record, identity, finding, earlier.pop(identity, None), publication
            )
        if not await self._current(job, record.inputs.head_sha):
            return None
        await self._resolve(job, record, earlier, publication)
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
        passed = not (findings or incomplete or publication.problems)
        return ("success" if passed else "neutral"), title

    def summary(
        self, outcome: ReviewOutcome, title: str, publication: Publication
    ) -> str:
        record = outcome.record
        inputs = record.inputs
        lines = [
            SUMMARY_MARKER,
            f"## rush review: {title}",
            "",
            f"Reviewed `{inputs.head_sha[:12]}` from `{inputs.merge_base_sha[:12]}`"
            f" (run `{record.id}`).",
            "",
            *((outcome.withheld, "") if outcome.withheld else ()),
        ]
        findings = record.progress.result.findings
        if findings:
            lines += [f"### Findings ({len(findings)})", ""]
            lines += [
                f"- **{item.severity.title()} {item.category}** {where(item)}: "
                + ("commented on the line" if item in publication.inline else "below")
                for item in findings
            ]
            lines.append("")
            for item in publication.in_summary:
                lines += [
                    safe_text(text) for text in ReviewReportService.finding_text(item)
                ]
        for name, reasons in _group(record.progress.result.limitations).items():
            lines += [f"### {name}", "", *(f"- {text}" for text in reasons), ""]
        if record.status == "failed":
            lines += ["### Execution error", "", record.progress.events[-1].reason, ""]
        if publication.problems:
            lines += ["### Publication problems", ""]
            lines += [f"- {text}" for text in publication.problems] + [""]
        if publication.resolved or publication.unchecked:
            lines += [
                f"Earlier findings: {publication.resolved} resolved after a recheck; "
                f"{publication.unchecked} not rechecked because this review was "
                "incomplete.",
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

    async def _finding(
        self,
        job: ReviewJob,
        record: ReviewRecord,
        identity: str,
        finding: Finding,
        comment: HostComment | None,
        publication: Publication,
    ) -> None:
        item, marker = f"finding:{identity}", f"<!-- rush:finding:{identity} -->"
        text = [safe_text(line) for line in ReviewReportService.finding_text(finding)]
        body = "\n".join([marker, *text])
        await self._store.plan(record.id, item, "review", self._clock())
        anchor = finding.anchor
        try:
            if comment is not None:
                if REASSESSMENT in comment.body:
                    # A challenge's verdict stays visible as the finding's history.
                    body += (
                        "\n\n" + REASSESSMENT + comment.body.split(REASSESSMENT, 1)[1]
                    )
                await self._edit(job, "review", comment.id, body)
                comment_id = comment.id
            else:
                placement = Placement(
                    record.inputs.head_sha, anchor.path, anchor.line, anchor.side
                )
                comment_id = await self._create(job, body, marker, placement)
        except PlacementError:
            publication.in_summary.append(finding)
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
    ) -> None:
        for comment in earlier.values():
            if RESOLVED in comment.body:
                continue
            if record.status != "completed":
                publication.unchecked += 1
                continue
            note = (
                f"{RESOLVED}\n**Resolved:** rush rechecked "
                f"`{record.inputs.head_sha[:12]}` and no longer reports this finding "
                "(it was fixed, waived by an approved exception, or withdrawn)."
            )
            try:
                await self._edit(job, "review", comment.id, f"{comment.body}\n\n{note}")
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
