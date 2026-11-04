import re
from collections import Counter
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal
from urllib.parse import quote, urlsplit

from app.core.errors import CodeHostError, PlacementError, PublicationUncertainError
from app.models.github import HostComment, Placement
from app.provider.github.abstract import CodeHostAbstract, CommentKind
from app.schemas.code_change import ChangeScope
from app.schemas.github import ReviewJob
from app.schemas.local_review import ReviewOutcome
from app.schemas.review import Finding, ReviewRecord
from app.services.ports import PublicationRepository
from app.services.review_markdown import finding_comment, heading, markdown
from app.services.review_markdown import safe_text as safe_text

SUMMARY_MARKER = "<!-- rush:summary -->"
LABEL_NAMES = {"bug": "bug", "possible_bug": "possible bug", "nitpick": "nitpick"}
FINDING = re.compile(r"<!-- rush:finding:([0-9a-f]{64}):(\d+) -->")
RESOLVED = "<!-- rush:resolved -->"
REASSESSMENT = "<!-- rush:reassessment -->"
HISTORY = "<!-- rush:history -->"
REOPENED = "<!-- rush:reopened -->"
WITHDRAWN = "<!-- rush:withdrawn -->"
REPORTED = re.compile(r"<!-- rush:reported:([0-9a-f]{40}|[0-9a-f]{64}) -->")
SUMMARY_LIMIT = 60000
NOT_RUN = "_Advisory review; no code or tests were run._"
Conclusion = Literal["success", "neutral", "failure"]


@dataclass
class Publication:
    inline: list[Finding] = field(default_factory=list)
    in_summary: list[Finding] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    resolved: int = 0
    unchecked: int = 0
    kept: int = 0
    links: dict[str, str] = field(default_factory=dict)


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


def _reported_at(comment: HostComment) -> str | None:
    original = comment.body.partition(HISTORY)[0]
    match = REPORTED.search(original)
    return match[1] if match else comment.commit


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


def _nothing_reviewed(record: ReviewRecord) -> bool:
    result = record.progress.result
    paths = {path for batch in result.batches for path in batch.paths}
    return bool(paths) and paths <= set(result.unreviewed_paths)


def _finding_line(
    finding: Finding, url: str, wording: str | None = None, limit: int = 240
) -> str:
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
    if len(problem) > limit:
        problem = problem[: limit - 1].rstrip() + "…"
    return f"- **{heading(finding)}** {link}: " + markdown(problem)


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
        elif _nothing_reviewed(record):
            title = "No file was reviewed for defects"
        else:
            title = "No supported problems found"
        if publication.problems:
            title += "; some results could not be published"
        if publication.unchecked and not incomplete:
            title += "; earlier findings not rechecked"
        if publication.kept and not incomplete:
            title += "; earlier findings still open"
        passed = not (
            findings
            or incomplete
            or publication.problems
            or publication.unchecked
            or publication.kept
            or _nothing_reviewed(record)
        )
        return ("success" if passed else "neutral"), title

    def summary(
        self, outcome: ReviewOutcome, title: str, publication: Publication
    ) -> str:
        """
        A short summary: the inline comments carry the findings, so this only
        says what was left, plus any finding that could not be placed inline.
        """
        record = outcome.record
        findings = record.progress.result.findings
        commit = f"`{record.inputs.head_sha[:12]}`"
        if findings:
            counts = Counter(finding.label for finding in findings)
            kinds = ", ".join(
                f"{counts[label]} {LABEL_NAMES[label]}"
                + ("s" if counts[label] != 1 else "")
                for label in ("bug", "possible_bug", "nitpick")
                if counts[label]
            )
            total = len(findings)
            headline = (
                f"{total} comment{'s' if total != 1 else ''} left for review on "
                f"{commit}: {kinds}."
            )
        else:
            # The check title says why: nothing found, incomplete, skipped,
            # nothing reviewed for defects, or could not run.
            headline = f"{safe_text(title).rstrip('.')} on {commit}."
        lines = [SUMMARY_MARKER, "## rush review", "", headline, ""]
        if outcome.withheld:
            lines += [outcome.withheld, ""]
        if findings and record.status not in {"completed", "failed", "skipped"}:
            lines += [
                "The review did not finish, so some changes may be unreviewed.",
                "",
            ]
        placed = {id(finding) for finding in publication.inline}
        unplaced = [
            (identity, finding)
            for identity, finding in _identities(findings)
            if id(finding) not in placed
        ]
        if unplaced:
            presentations = {
                item.finding_id: item.wording.problem
                for item in record.progress.result.presentations
            }
            lines += ["Could not be placed on a line:", ""]
            lines += [
                _finding_line(
                    finding,
                    publication.links.get(identity, ""),
                    presentations.get(finding.id),
                )
                for identity, finding in unplaced
            ] + [""]
        if publication.problems:
            lines += ["Some comments could not be published.", ""]
        earlier = [
            text
            for count, text in (
                (publication.resolved, f"{publication.resolved} resolved"),
                (publication.unchecked, f"{publication.unchecked} not rechecked"),
                (publication.kept, f"{publication.kept} still open"),
            )
            if count
        ]
        if earlier:
            lines += [f"Earlier comments: {', '.join(earlier)}.", ""]
        text = "\n".join(lines)
        if len(text) > SUMMARY_LIMIT:
            text = text[:SUMMARY_LIMIT] + "\n\n_The rest was cut to fit._"
        return f"{text}\n\n{NOT_RUN}"

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
        hunks = {
            f"diff:{hunk.id}": (
                file.old_path or file.new_path or "",
                file.new_path or file.old_path or "",
                hunk,
            )
            for file in (scope.files if scope else ())
            for hunk in file.hunks
        }
        body = (
            f"{marker}\n<!-- rush:reported:{record.inputs.head_sha} -->\n"
            + finding_comment(finding, presentation, hunks)
        )
        await self._store.plan(record.id, item, "review", self._clock())
        try:
            if comment is not None:
                body = _history(body, comment.body, record.inputs.head_sha)
                await self._edit(job, "review", comment.id, body)
                comment_id = comment.id
            else:
                comment_id = await self._place(
                    job, body, marker, self._placement(record, finding, scope)
                )
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
        waived = {item.finding.fingerprint for item in record.progress.result.waived}
        for identity, comment in earlier.items():
            if resolved(comment.body):
                continue
            if record.status != "completed" or (
                comment.path is not None and comment.path in excluded
            ):
                publication.unchecked += 1
                continue
            # Model recall varies between runs, so a finding missing from a rerun
            # of the same commit is not evidence that it was fixed; a waiver or a
            # withdrawal after a challenge still is.
            if (
                _reported_at(comment) == record.inputs.head_sha
                and identity.partition(":")[0] not in waived
                and WITHDRAWN not in comment.body
            ):
                publication.kept += 1
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

    async def _place(
        self, job: ReviewJob, body: str, marker: str, placement: Placement
    ) -> int:
        """
        Place a finding inline: on its lines, else on its last line, else on the
        whole file; only if all fail does it stay in the summary alone.
        """
        attempts = [placement]
        if placement.start_line is not None:
            attempts.append(replace(placement, start_line=None))
        attempts.append(replace(placement, start_line=None, file_level=True))
        for attempt in attempts[:-1]:
            with suppress(PlacementError):
                return await self._create(job, body, marker, attempt)
        return await self._create(job, body, marker, attempts[-1])

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
