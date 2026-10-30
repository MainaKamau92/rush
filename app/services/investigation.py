import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import TypeVar

from app.core.errors import ChangeError, InvestigationError
from app.models.code_change import RepositoryFile
from app.models.repository_path import safe_repository_path
from app.provider.repository.abstract import CodeRepositoryAbstract
from app.schemas.code_change import ChangeScope, FileChange, Omission
from app.schemas.investigation import (
    InvestigationReport,
    Question,
    ReadAudit,
    ReadRequest,
    Snippet,
)
from app.schemas.review import Limitation, ReviewLimits
from app.services.code_change_reader import MAX_FILE_BYTES, CodeChangeReaderService
from app.services.code_relationships import verifies_relationship
from app.services.review_budget import BudgetExceededError, ReviewBudget

Result = TypeVar("Result")
MAX_SNIPPET_LINES = 80


class InvestigationService:
    def __init__(
        self,
        repository: CodeRepositoryAbstract,
        reader: CodeChangeReaderService,
        budget: ReviewBudget,
        *,
        search_paths: frozenset[str] = frozenset(),
        approved_test_paths: frozenset[str] = frozenset(),
    ) -> None:
        self._repository, self._reader, self._budget = repository, reader, budget
        self._search_paths = frozenset(search_paths)
        self._approved_tests = frozenset(approved_test_paths)
        self._scope: ChangeScope | None = None
        self._started = self._finished = False
        self._questions: dict[str, Question] = {}
        self._reads: list[ReadAudit] = []
        self._snippets: dict[str, Snippet] = {}
        self._files: dict[str, RepositoryFile] = {}
        self._extra_files: set[str] = set()
        self._problems: list[Limitation] = []

    async def start(
        self,
        head: str,
        *,
        target: str | None = None,
        base: str | None = None,
    ) -> InvestigationReport:
        if self._started:
            raise InvestigationError("An investigation cannot be restarted")
        self._started = True
        try:
            scope = await self._budget.perform(
                lambda: self._reader.read(head, target=target, base=base)
            )
            self._scope = self._admit(scope)
        except BudgetExceededError:
            pass
        return self.report()

    def _admit(self, scope: ChangeScope) -> ChangeScope:
        files: list[FileChange] = []
        omitted = list(scope.omissions)
        for _ in omitted:
            with suppress(BudgetExceededError):
                self._budget.charge("changed_files")
        for file in scope.files:
            try:
                self._budget.charge("changed_files")
                self._budget.charge("changed_lines", file.additions + file.deletions)
                text = "\n".join(
                    line.text for hunk in file.hunks for line in hunk.lines
                )
                self._budget.charge("source_bytes", len(text.encode()))
                files.append(file)
            except BudgetExceededError as error:
                omitted.append(
                    Omission(
                        reason="budget",
                        old_path=file.old_path,
                        new_path=file.new_path,
                        detail=str(error),
                    )
                )
        return scope.model_copy(
            update={"files": tuple(files), "omissions": tuple(omitted)}
        )

    def _active(self) -> ChangeScope:
        if not self._started or self._scope is None or self._finished:
            raise InvestigationError("Investigation is not active")
        return self._scope

    @property
    def limits(self) -> ReviewLimits:
        return self._budget.limits

    @property
    def active_scope(self) -> ChangeScope:
        return self._active()

    def open_question(
        self,
        question_id: str,
        question: str,
        origin_hunk_id: str,
        *,
        required: bool = True,
    ) -> None:
        scope = self._active()
        if question_id in self._questions:
            raise InvestigationError("Question identity already exists")
        if any(
            item.origin_hunk_id == origin_hunk_id
            and " ".join(item.question.lower().split())
            == " ".join(question.lower().split())
            for item in self._questions.values()
        ):
            raise InvestigationError("This question is already registered or answered")
        if not any(
            hunk.id == origin_hunk_id for file in scope.files for hunk in file.hunks
        ):
            raise InvestigationError("Question must originate in the admitted change")
        self._questions[question_id] = Question(
            id=question_id,
            question=question,
            origin_hunk_id=origin_hunk_id,
            required=required,
        )

    def answer(
        self, question_id: str, answer: str, evidence_ids: tuple[str, ...]
    ) -> None:
        self._active()
        if self._budget.active_operations:
            raise InvestigationError("Wait for active operations before answering")
        question = self._questions.get(question_id)
        if question is None or question.answer is not None or not evidence_ids:
            raise InvestigationError("An open question and read evidence are required")
        if any(
            read_id not in self._snippets
            or self._snippets[read_id].question_id != question_id
            for read_id in evidence_ids
        ):
            raise InvestigationError(
                "Answers must cite this question's successful reads"
            )
        self._questions[question_id] = Question(
            **(question.model_dump() | {"answer": answer, "evidence_ids": evidence_ids})
        )

    async def read(self, request: ReadRequest) -> ReadAudit:
        self._active()
        try:
            source, start, end, depth = self._origin(request)
            self._budget.depth(depth)
            incoming = request.relationship in {"caller", "test"}
            if (
                source not in self._files
                or incoming
                and request.target not in self._files
            ):
                self._budget.charge("scoped_searches")
            target_text = None
            if incoming:
                if (
                    request.target not in self._search_paths
                    and request.target not in self._files
                ):
                    raise InvestigationError(
                        "Incoming links require a host-approved scoped search"
                    )
                target_text = await self._search(request.target, request)
            source_text = await self._search(source, request)
            valid = await self._budget.perform(
                lambda: asyncio.to_thread(
                    verifies_relationship,
                    source,
                    source_text,
                    request.target,
                    request.relationship,
                    start,
                    end,
                    target_text,
                )
            )
            if not valid:
                raise InvestigationError(
                    "The stated direct relationship is not supported by code"
                )
            return await self._read_target(request, depth, (source, start, end))
        except (InvestigationError, ChangeError) as error:
            if request.question_id not in self._questions:
                self._problems.append(
                    Limitation(code="unresolved_question", reason=str(error))
                )
            audit = ReadAudit(
                request=request, action="denied", path=request.target, reason=str(error)
            )
            self._reads.append(audit)
            return audit

    def _origin(self, request: ReadRequest) -> tuple[str, int, int, int]:
        scope = self._active()
        question = self._questions.get(request.question_id)
        if question is None or (question.question, question.origin_hunk_id) != (
            request.question,
            request.origin_hunk_id,
        ):
            raise InvestigationError(
                "Read must match a registered change-specific question"
            )
        if question.answer is not None:
            raise InvestigationError(
                "The question is answered; further reads are refused"
            )
        if not safe_repository_path(request.target):
            raise InvestigationError("Target must stay inside this repository")
        if (
            request.end_line < request.start_line
            or request.end_line - request.start_line >= MAX_SNIPPET_LINES
        ):
            raise InvestigationError("Request a valid snippet of at most 80 lines")
        if (
            _is_test(request.target)
            and request.relationship != "test"
            and request.target not in self._approved_tests
        ):
            raise InvestigationError(
                "Application tests need a specific test relationship or approved rule"
            )
        if request.parent_read_id:
            parent = self._snippets.get(request.parent_read_id)
            if parent is None or parent.question_id != question.id:
                raise InvestigationError("Parent read must belong to this question")
            return parent.path, parent.start_line, parent.end_line, parent.depth + 1
        path, start, end = _changed_origin(scope, request.origin_hunk_id)
        return path, start, end, 1

    async def _load(self, path: str) -> RepositoryFile:
        scope = self._active()
        changed = {file.new_path for file in scope.files}
        if path not in changed and path not in self._extra_files:
            self._budget.charge("additional_files")
            self._extra_files.add(path)
        self._budget.charge("snippet_reads")
        if path in self._files:
            file = self._files[path]
            self._budget.charge("source_bytes", len(file.content or b""))
            return file
        cap = min(MAX_FILE_BYTES, self._budget.remaining("source_bytes"))
        file = await self._budget.perform(
            lambda: self._repository.file(scope.head_sha, path, cap)
        )
        if file.mode not in {"100644", "100755"}:
            raise InvestigationError(
                "Related entry is not a regular file; nothing is followed"
            )
        if file.content is None:
            if cap < MAX_FILE_BYTES:
                self._budget.charge("source_bytes", cap + 1)
            raise InvestigationError("Related file exceeds the supported size")
        self._budget.charge("source_bytes", len(file.content))
        if b"\0" in file.content:
            raise InvestigationError("Related binary content is unsupported")
        try:
            file.content.decode()
        except UnicodeDecodeError as error:
            raise InvestigationError("Related content is not UTF-8") from error
        self._files[path] = file
        return file

    async def _search(self, path: str, request: ReadRequest) -> str:
        if path not in self._files:
            self._reads.append(
                ReadAudit(
                    request=request,
                    action="scoped_search",
                    path=path,
                    reason="Resolve the named relationship in this frozen file only",
                )
            )
            await self._load(path)
        content = self._files[path].content
        return content.decode() if content is not None else ""

    async def _read_target(
        self, request: ReadRequest, depth: int, origin: tuple[str, int, int]
    ) -> ReadAudit:
        file = await self._load(request.target)
        lines = (file.content or b"").decode().splitlines(keepends=True)
        if request.start_line > len(lines):
            raise InvestigationError("Requested snippet is outside the file")
        end = min(request.end_line, len(lines))
        snippet = Snippet(
            id=f"read-{len(self._snippets) + 1}",
            question_id=request.question_id,
            origin_hunk_id=request.origin_hunk_id,
            path=request.target,
            commit=self._active().head_sha,
            object_id=file.object_id,
            start_line=request.start_line,
            end_line=end,
            text="".join(lines[request.start_line - 1 : end]),
            depth=depth,
        )
        self._snippets[snippet.id] = snippet
        audit = ReadAudit(
            request=request,
            action="read",
            path=request.target,
            reason="Verified direct relationship",
            snippet=snippet,
            source_path=origin[0],
            source_start_line=origin[1],
            source_end_line=origin[2],
            source_object_id=self._files[origin[0]].object_id,
        )
        self._reads.append(audit)
        return audit

    async def call_model(self, operation: Callable[[], Awaitable[Result]]) -> Result:
        self._active()
        self._budget.charge("model_calls")
        return await self._budget.perform(operation)

    def supply_context(self, text: str, *, required: bool = True) -> str:
        self._active()
        try:
            self._budget.charge("source_bytes", len(text.encode()))
        except BudgetExceededError as error:
            if required:
                self._problems.append(
                    Limitation(code="missing_context", reason=str(error))
                )
            raise
        return text

    async def call_mcp(
        self,
        operation: Callable[[], Awaitable[Result]],
        *,
        scoped_search: bool = False,
        required: bool = True,
    ) -> Result:
        self._active()
        try:
            self._budget.charge("mcp_calls")
            if scoped_search:
                self._budget.charge("scoped_searches")
            return await self._budget.perform(operation)
        except BudgetExceededError as error:
            if required:
                self._problems.append(
                    Limitation(code="missing_context", reason=str(error))
                )
            raise

    def report(self) -> InvestigationReport:
        if not self._started:
            raise InvestigationError("Investigation has not started")
        with suppress(BudgetExceededError):
            self._budget.seconds_left()
        limitations = [*self._problems, *self._budget.limitations]
        if self._scope:
            limitations.extend(self._scope.limitations())
        else:
            limitations.append(
                Limitation(
                    code="scope_excluded",
                    reason="Change discovery did not produce an admitted scope",
                )
            )
        limitations.extend(
            Limitation(
                code="unresolved_question",
                reason=question.question,
                affects_completeness=question.required,
            )
            for question in self._questions.values()
            if question.answer is None
        )
        return InvestigationReport(
            scope=self._scope,
            questions=tuple(self._questions.values()),
            reads=tuple(self._reads),
            counters=self._budget.snapshot(),
            elapsed_seconds=self._budget.elapsed_seconds,
            limitations=tuple(limitations),
        )

    def finish(self) -> InvestigationReport:
        if self._budget.active_operations:
            raise InvestigationError("Wait for active operations before finishing")
        if not self._started or self._finished:
            raise InvestigationError(
                "Investigation has not started or is already finished"
            )
        self._finished = True
        return self.report()


def _is_test(path: str) -> bool:
    parts = path.split("/")
    return (
        "tests" in parts
        or "test" in parts
        or parts[-1].startswith("test_")
        or parts[-1].endswith("_test.py")
    )


def _changed_origin(scope: ChangeScope, origin_hunk_id: str) -> tuple[str, int, int]:
    for file in scope.files:
        for hunk in file.hunks:
            if hunk.id == origin_hunk_id and file.new_path:
                changed = [
                    line.new_line
                    for line in hunk.lines
                    if line.kind == "added" and line.new_line
                ]
                if changed:
                    return file.new_path, min(changed), max(changed)
    raise InvestigationError("No changed head-side code supports this question")
