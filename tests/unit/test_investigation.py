import asyncio
from dataclasses import replace

import pytest

from app.core.errors import ChangeError, InvestigationError, MissingObjectError
from app.models.code_change import RepositoryFile
from app.schemas.code_change import ChangeLine, ChangeScope, FileChange, Hunk
from app.schemas.investigation import ReadRequest
from app.schemas.review import ReviewLimits
from app.services.code_relationships import verifies_relationship
from app.services.investigation import InvestigationService
from app.services.review_budget import BudgetExceededError, ReviewBudget

HEAD = "b" * 40
SOURCE = "from store import lookup\n\ndef customer_name():\n    return lookup()\n"
STORE = "from leaf import value\n\ndef lookup():\n    return value()\n"


class Clock:
    value = 0.0

    def __call__(self):
        return self.value


def scope():
    return ChangeScope(
        comparison="exact",
        target_sha=None,
        base_sha="a" * 40,
        head_sha=HEAD,
        omissions=(),
        files=(
            FileChange(
                status="modified",
                old_path="customers.py",
                new_path="customers.py",
                old_object="c" * 40,
                new_object="d" * 40,
                old_mode="100644",
                new_mode="100644",
                additions=1,
                deletions=1,
                hunks=(
                    Hunk(
                        id="lookup-hunk",
                        old_start=4,
                        old_lines=1,
                        new_start=4,
                        new_lines=1,
                        lines=(
                            ChangeLine(
                                kind="removed", old_line=4, text="    return None"
                            ),
                            ChangeLine(
                                kind="added", new_line=4, text="    return lookup()"
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


class Repository:
    def __init__(self):
        self.files = {
            "customers.py": RepositoryFile(
                "customers.py", "d" * 40, "100644", SOURCE.encode()
            ),
            "store.py": RepositoryFile("store.py", "e" * 40, "100644", STORE.encode()),
            "leaf.py": RepositoryFile(
                "leaf.py", "f" * 40, "100644", b"def value():\n    return 1\n"
            ),
            "test_customer.py": RepositoryFile(
                "test_customer.py",
                "1" * 40,
                "100644",
                b"from customers import customer_name\n"
                b"def test_name():\n    customer_name()\n",
            ),
        }
        self.calls = []

    async def file(self, commit, path, limit):
        self.calls.append((commit, path))
        if path not in self.files:
            raise MissingObjectError("Related file unavailable")
        file = self.files[path]
        if file.content is not None and len(file.content) > limit:
            return replace(file, content=None)
        return file


class Reader:
    def __init__(self):
        self.scope = scope()

    async def read(self, *args, **kwargs):
        return self.scope


def make_service(limits=None, **kwargs):
    clock, repository, reader = Clock(), Repository(), Reader()
    budget = ReviewBudget(limits or ReviewLimits(), clock)
    service = InvestigationService(repository, reader, budget, **kwargs)
    return service, repository, reader, clock


def request(**changes):
    return ReadRequest(
        **(
            {
                "question_id": "lookup",
                "question": "Does the lookup keep the tenant boundary?",
                "origin_hunk_id": "lookup-hunk",
                "relationship": "callee",
                "target": "store.py",
                "expected_evidence": "The called query's tenant condition",
                "start_line": 1,
                "end_line": 4,
            }
            | changes
        )
    )


def open_question(service, *, required=True):
    item = request()
    service.open_question(
        item.question_id, item.question, item.origin_hunk_id, required=required
    )


async def test_question_provenance_snippets_and_stopping_condition():
    service, repository, _, _ = make_service()
    await service.start("head", base="base")
    open_question(service)
    outcome = await service.read(request())
    assert outcome.action == "read" and outcome.snippet.depth == 1
    assert outcome.snippet.commit == HEAD
    assert outcome.snippet.text == STORE
    assert repository.calls == [(HEAD, "customers.py"), (HEAD, "store.py")]
    service.answer(
        "lookup", "The lookup follows the unscoped helper", (outcome.snippet.id,)
    )
    stopped = await service.read(request())
    assert stopped.action == "denied" and "answered" in stopped.reason
    assert len(repository.calls) == 2
    report = service.finish()
    assert report.complete and report.questions[0].answer
    assert [audit.action for audit in report.reads] == [
        "scoped_search",
        "read",
        "denied",
    ]
    assert all(audit.request.expected_evidence for audit in report.reads)


async def test_guessed_unrelated_dependency_is_not_read_and_question_stays_visible():
    service, repository, _, _ = make_service()
    await service.start("head", base="base")
    open_question(service)
    denied = await service.read(request(target="billing.py"))
    assert denied.action == "denied" and "not supported" in denied.reason
    assert repository.calls == [(HEAD, "customers.py")]
    report = service.finish()
    assert not report.complete
    assert report.limitations[-1].code == "unresolved_question"


@pytest.mark.parametrize(
    "changes",
    [
        {"target": "../other/repo.py"},
        {"target": "/etc/passwd"},
        {"target": ".git/config"},
        {"start_line": 5, "end_line": 4},
        {"parent_read_id": "missing"},
        {"question": "Different question"},
        {"origin_hunk_id": "unrelated"},
    ],
)
async def test_invalid_requests_do_not_access_repository(changes):
    service, repository, _, _ = make_service()
    await service.start("head", base="base")
    open_question(service)
    assert (await service.read(request(**changes))).action == "denied"
    assert repository.calls == []
    assert not service.finish().complete


async def test_unknown_questions_and_invalid_lifecycle_do_not_look_complete():
    service, repository, _, _ = make_service()
    with pytest.raises(InvestigationError):
        service.report()
    with pytest.raises(InvestigationError):
        service.finish()
    await service.start("head", base="base")
    with pytest.raises(InvestigationError):
        await service.start("head", base="base")
    with pytest.raises(InvestigationError):
        service.open_question("q", "Why?", "not-a-hunk")
    assert (await service.read(request())).action == "denied"
    assert not service.finish().complete and not repository.calls
    with pytest.raises(InvestigationError):
        await service.call_model(lambda: asyncio.sleep(0))
    with pytest.raises(InvestigationError):
        service.finish()


async def test_answer_requires_real_evidence_for_the_same_question():
    service, _, _, _ = make_service()
    await service.start("head", base="base")
    open_question(service)
    with pytest.raises(InvestigationError):
        open_question(service)
    with pytest.raises(InvestigationError):
        service.answer("lookup", "Guess", ())
    with pytest.raises(InvestigationError):
        service.answer("lookup", "Guess", ("unknown",))
    outcome = await service.read(request())
    service.open_question("other", "Another query?", "lookup-hunk")
    with pytest.raises(InvestigationError):
        service.answer("other", "Guess", (outcome.snippet.id,))


async def test_depth_is_derived_from_successful_parent_reads():
    service, repository, _, _ = make_service()
    await service.start("head", base="base")
    open_question(service)
    first = await service.read(request())
    second = await service.read(
        request(target="leaf.py", parent_read_id=first.snippet.id, end_line=2)
    )
    assert second.snippet.depth == 2
    before = len(repository.calls)
    third = await service.read(
        request(target="store.py", parent_read_id=second.snippet.id)
    )
    assert third.action == "denied" and "relationship_depth" in third.reason
    assert len(repository.calls) == before
    assert not service.finish().complete


@pytest.mark.parametrize(
    "kind", ["binary", "encoding", "symlink", "large", "missing", "range"]
)
async def test_unsupported_related_content_is_explicit(kind):
    service, repository, _, _ = make_service()
    existing = repository.files["store.py"]
    updates = {
        "binary": replace(existing, content=b"\0binary"),
        "encoding": replace(existing, content=b"\xff"),
        "symlink": replace(existing, mode="120000", content=None),
        "large": replace(existing, content=b"x" * 200_000),
    }
    if kind in updates:
        repository.files["store.py"] = updates[kind]
    if kind == "missing":
        repository.files.pop("store.py")
    await service.start("head", base="base")
    open_question(service)
    arguments = {"start_line": 40, "end_line": 50} if kind == "range" else {}
    outcome = await service.read(request(**arguments))
    assert outcome.action == "denied" and outcome.snippet is None
    assert not service.finish().complete


async def test_application_tests_need_a_proven_specific_link_or_host_rule():
    service, repository, _, _ = make_service(
        search_paths=frozenset({"test_customer.py"})
    )
    await service.start("head", base="base")
    open_question(service)
    denied = await service.read(
        request(target="test_customer.py", relationship="import")
    )
    assert denied.action == "denied" and repository.calls == []
    outcome = await service.read(
        request(target="test_customer.py", relationship="test")
    )
    assert outcome.action == "read"
    service.answer(
        "lookup",
        "The direct test exercises the changed customer function",
        (outcome.snippet.id,),
    )
    assert service.finish().complete


async def test_unknown_callers_cannot_start_an_arbitrary_search():
    service, repository, _, _ = make_service()
    await service.start("head", base="base")
    open_question(service)
    outcome = await service.read(request(target="billing.py", relationship="caller"))
    assert outcome.action == "denied" and repository.calls == []


@pytest.mark.parametrize("limit", ["changed_files", "changed_lines", "source_bytes"])
async def test_initial_scope_limits_record_every_excluded_file(limit):
    settings = {"changed_files": 1} if limit == "changed_files" else {limit: 1}
    service, _, reader, _ = make_service(ReviewLimits(**settings))
    if limit == "changed_files":
        extra = reader.scope.files[0].model_copy(update={"new_path": "another.py"})
        reader.scope = reader.scope.model_copy(
            update={"files": (*reader.scope.files, extra)}
        )
    report = await service.start("head", base="base")
    assert not report.complete and len(report.scope.omissions) == 1
    assert report.scope.omissions[0].reason == "budget"
    assert any(item.code == "scope_excluded" for item in report.limitations)


@pytest.mark.parametrize(
    "resource", ["additional_files", "snippet_reads", "scoped_searches"]
)
async def test_read_budgets_refuse_io_and_preserve_the_question(resource):
    service, repository, _, _ = make_service(ReviewLimits(**{resource: 0}))
    await service.start("head", base="base")
    open_question(service)
    outcome = await service.read(request())
    assert outcome.action == "denied" and resource in outcome.reason
    if resource != "additional_files":
        assert not repository.calls
    assert not service.finish().complete


async def test_call_attempts_and_retries_share_limits_and_context_byte_budget():
    service, _, _, _ = make_service(ReviewLimits(model_calls=1, mcp_calls=1))
    await service.start("head", base="base")
    attempted = []

    async def fails():
        attempted.append(True)
        raise RuntimeError("Controlled outside failure")

    for call in (service.call_model, service.call_mcp):
        with pytest.raises(RuntimeError):
            await call(fails)
        with pytest.raises(BudgetExceededError):
            await call(fails)
    assert len(attempted) == 2
    assert service.supply_context("approved excerpt") == "approved excerpt"
    with pytest.raises(BudgetExceededError):
        service.supply_context("x" * 200_000)
    assert not service.finish().complete


async def test_elapsed_time_and_cancellation_stop_callbacks():
    service, _, _, clock = make_service(ReviewLimits(wall_seconds=1))
    await service.start("head", base="base")
    cancelled = []
    clock.value = 0.995

    async def slow():
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)

    with pytest.raises(BudgetExceededError):
        await service.call_model(slow)
    with pytest.raises(BudgetExceededError):
        await service.call_mcp(slow)
    assert cancelled == [True] and not service.finish().complete


async def test_external_cancellation_propagates_and_scoped_mcp_search_counts():
    service, _, _, _ = make_service()
    await service.start("head", base="base")

    async def cancel():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await service.call_model(cancel)
    assert (
        await service.call_mcp(
            lambda: asyncio.sleep(0, result="public"), scoped_search=True
        )
        == "public"
    )
    with pytest.raises(BudgetExceededError):
        await service.call_mcp(cancel, scoped_search=True)


async def test_deadline_during_initial_scope_discovery_is_partial():
    service, _, reader, clock = make_service(ReviewLimits(wall_seconds=1))

    async def delayed(*args, **kwargs):
        clock.value = 2
        return scope()

    reader.read = delayed
    report = await service.start("head", base="base")
    assert report.scope is None and not report.complete
    assert "wall_seconds" in report.limitations[0].reason


def test_budget_counters_cannot_be_refunded():
    budget = ReviewBudget(ReviewLimits(), Clock())
    with pytest.raises(InvestigationError):
        budget.charge("model_calls", -1)


@pytest.mark.parametrize(
    ("source", "target", "relationship", "target_source", "expected"),
    [
        (
            "import store\ndef f():\n return store.lookup()\n",
            "store.py",
            "callee",
            None,
            True,
        ),
        (
            "from pkg.store import lookup as x\ndef f():\n return x()\n",
            "pkg/store.py",
            "import",
            None,
            True,
        ),
        (
            "from .store import lookup\ndef f():\n return lookup()\n",
            "pkg/store.py",
            "import",
            None,
            True,
        ),
        (
            "from schema import Customer\ndef f(x: Customer):\n return x\n",
            "schema.py",
            "shared_interface",
            None,
            True,
        ),
        (
            "def f():\n return open('settings.json').read()\n",
            "settings.json",
            "configuration",
            None,
            True,
        ),
        (
            "def f():\n return open(dynamic).read()\n",
            "settings.json",
            "configuration",
            None,
            False,
        ),
        (
            "def f():\n return open('billing.py').read()\n",
            "billing.py",
            "configuration",
            None,
            False,
        ),
        (
            "def f():\n return helper()\ndef helper():\n return 1\n",
            "pkg/service.py",
            "callee",
            None,
            True,
        ),
        (
            "def f():\n return 1\n",
            "caller.py",
            "caller",
            "from pkg.service import f\ndef x():\n return f()\n",
            True,
        ),
        (
            "def f():\n return 1\n",
            "caller.py",
            "caller",
            "import pkg.service as service\ndef x():\n return service.f()\n",
            True,
        ),
        (
            "def f():\n return 1\n",
            "caller.py",
            "caller",
            "from unrelated import f\ndef x():\n return f()\n",
            False,
        ),
        ("def f():\n return 1\n", "caller.py", "caller", None, False),
        (
            "from store import lookup\ndef f(lookup):\n return lookup()\n",
            "store.py",
            "callee",
            None,
            False,
        ),
        (
            "from store import lookup\ndef f():\n lookup = other\n return lookup()\n",
            "store.py",
            "callee",
            None,
            False,
        ),
        ("def invalid(", "store.py", "import", None, False),
    ],
)
def test_relationship_proofs_use_code_rather_than_names_in_prose(
    source, target, relationship, target_source, expected
):
    assert (
        verifies_relationship(
            "pkg/service.py", source, target, relationship, 1, 80, target_source
        )
        == expected
    )


@pytest.mark.parametrize(
    "source",
    [
        "from store import lookup\nfrom billing import lookup\n"
        "def f():\n return lookup()\n",
        "from store import lookup\nlookup = other\ndef f():\n return lookup()\n",
        "from store import lookup\ndef f():\n def unused():\n"
        "  return lookup()\n return 1\n",
        "from ..store import lookup\ndef f():\n return lookup()\n",
    ],
)
def test_ambiguous_imports_and_unused_closures_are_not_direct_proofs(source):
    assert not verifies_relationship(
        "pkg/service.py", source, "store.py", "callee", 3, 20
    )


def test_other_class_methods_do_not_authorize_a_read_for_the_changed_method():
    source = (
        "from billing import lookup\nclass Customers:\n"
        " def unrelated(self):\n  return lookup()\n"
        " def changed(self):\n  return 1\n"
    )
    assert not verifies_relationship(
        "customers.py", source, "billing.py", "callee", 6, 6
    )
    assert not verifies_relationship(
        "customers.js", source, "billing.py", "callee", 6, 6
    )


async def test_provider_timeout_is_not_mistaken_for_the_review_deadline():
    service, _, _, _ = make_service()
    await service.start("head", base="base")

    async def provider_timeout():
        raise TimeoutError("Provider timed out before the review deadline")

    with pytest.raises(TimeoutError):
        await service.call_model(provider_timeout)
    assert await service.call_model(lambda: asyncio.sleep(0, result="ok")) == "ok"
    assert not any(
        "wall_seconds" in item.reason for item in service.report().limitations
    )


@pytest.mark.parametrize("required", [True, False])
async def test_context_exhaustion_distinguishes_required_work_from_optional_notes(
    required,
):
    service, _, _, _ = make_service(ReviewLimits(source_bytes=100))
    await service.start("head", base="base")
    with pytest.raises(BudgetExceededError):
        service.supply_context("x" * 1000, required=required)
    assert service.finish().complete != required


async def test_an_answered_question_cannot_be_reopened_with_another_id():
    service, _, _, _ = make_service()
    await service.start("head", base="base")
    open_question(service)
    result = await service.read(request())
    service.answer("lookup", "The query is unscoped", (result.snippet.id,))
    with pytest.raises(InvestigationError, match="already registered or answered"):
        service.open_question(
            "another-id", request().question.upper(), request().origin_hunk_id
        )


async def test_session_cannot_finish_or_answer_during_an_inflight_operation():
    service, _, _, _ = make_service()
    await service.start("head", base="base")
    started = asyncio.Event()
    release = asyncio.Event()

    async def pending():
        started.set()
        await release.wait()

    task = asyncio.create_task(service.call_model(pending))
    await started.wait()
    with pytest.raises(InvestigationError, match="active operations"):
        service.finish()
    with pytest.raises(InvestigationError, match="active operations"):
        service.answer("q1", "Too early", ("read-1",))
    release.set()
    await task
    assert service.finish().complete


@pytest.mark.parametrize(
    "body",
    [
        "from billing import lookup\n return lookup()",
        "def lookup():\n  return None\n return lookup()",
        "try:\n  return 1\n except Exception as lookup:\n  return lookup()",
    ],
)
def test_local_binding_changes_do_not_authorize_the_imported_callee(body):
    source = "from store import lookup\ndef f():\n " + body + "\n"
    assert not verifies_relationship("service.py", source, "store.py", "callee", 3, 20)


@pytest.mark.parametrize(
    "source, expected",
    [
        ("from pathlib import Path\ndef f():\n return Path('settings.toml')\n", True),
        ("from billing import Path\ndef f():\n return Path('settings.toml')\n", False),
        ("def f(open):\n return open('settings.toml')\n", False),
    ],
)
def test_configuration_requires_a_supported_file_accessor(source, expected):
    assert (
        verifies_relationship(
            "service.py", source, "settings.toml", "configuration", 2, 20
        )
        == expected
    )


def test_a_class_method_is_not_a_module_export_for_reverse_links():
    source = "class Customers:\n def find(self):\n  return 1\n"
    caller = "from customers import find\ndef main():\n return find()\n"
    assert not verifies_relationship(
        "customers.py", source, "caller.py", "caller", 3, 3, caller
    )


async def test_failed_discovery_never_leaves_a_clean_empty_scope(monkeypatch):
    service, _, reader, _ = make_service()

    async def missing_revision(*args, **kwargs):
        raise ChangeError("The head revision is unavailable")

    monkeypatch.setattr(reader, "read", missing_revision)
    with pytest.raises(ChangeError, match="unavailable"):
        await service.start("head", base="base")
    result = service.finish()
    assert not result.complete and result.scope is None
    assert any(item.code == "scope_excluded" for item in result.limitations)


@pytest.mark.parametrize(
    "source, relationship, target",
    [
        (
            "from store import lookup\nfrom billing import *\n"
            "def f():\n return lookup()\n",
            "callee",
            "store.py",
        ),
        (
            "from billing import *\ndef f():\n return open('settings.toml')\n",
            "configuration",
            "settings.toml",
        ),
        (
            "def open(value):\n return value\n"
            "def f():\n return open('settings.toml')\n",
            "configuration",
            "settings.toml",
        ),
    ],
)
def test_wildcard_imports_and_replaced_accessors_do_not_prove_an_edge(
    source, relationship, target
):
    assert not verifies_relationship("service.py", source, target, relationship, 3, 20)


async def test_an_over_long_window_is_trimmed_to_eighty_lines():
    service, _, _, _ = make_service()
    await service.start("head", base="base")
    open_question(service)
    outcome = await service.read(request(start_line=1, end_line=1000))
    assert outcome.action == "read"
    assert outcome.request.end_line == 80


async def test_the_rest_of_a_changed_file_is_readable_in_any_language():
    service, repository, reader, _ = make_service()
    tsx = "export function View() {\n  return null;\n}\n"
    (file,) = reader.scope.files
    reader.scope = reader.scope.model_copy(
        update={
            "files": (
                file.model_copy(update={"old_path": "v.tsx", "new_path": "v.tsx"}),
            )
        }
    )
    repository.files["v.tsx"] = RepositoryFile(
        "v.tsx", "d" * 40, "100644", tsx.encode()
    )
    await service.start("head", base="base")
    open_question(service)
    # No link can be proved from a TypeScript change, but its own file is in scope.
    same = await service.read(
        request(target="v.tsx", relationship="shared_interface", end_line=3)
    )
    assert same.action == "read" and same.reason == "Same changed file"
    assert same.snippet.text == tsx
    other = await service.read(request(target="store.py"))
    assert other.action == "denied"
    assert "not supported" in other.reason


async def test_only_an_ignored_changed_file_can_be_fetched_for_a_summary():
    from app.schemas.code_change import Omission

    service, repository, reader, _ = make_service()
    renamed = Omission(
        reason="ignored",
        old_path="old-lock.json",
        new_path="package-lock.json",
        detail="Ignored by the operator",
        intentional=True,
    )
    reader.scope = reader.scope.model_copy(update={"omissions": (renamed,)})
    repository.files["old-lock.json"] = RepositoryFile(
        "old-lock.json", "8" * 40, "100644", b"old"
    )
    repository.files["package-lock.json"] = RepositoryFile(
        "package-lock.json", "9" * 40, "100644", b"new"
    )
    await service.start("head", base="base")
    # A renamed lockfile is compared with its old path on the base side.
    assert await service.ignored_versions(renamed) == (b"old", b"new")
    added = renamed.model_copy(update={"old_path": None})
    with pytest.raises(InvestigationError, match="Only an ignored"):
        await service.ignored_versions(added)
    reader.scope = reader.scope.model_copy(update={"omissions": (added,)})
    service, repository, reader2, _ = make_service()
    reader2.scope = reader.scope
    repository.files["package-lock.json"] = RepositoryFile(
        "package-lock.json", "9" * 40, "100644", b"new"
    )
    await service.start("head", base="base")
    assert await service.ignored_versions(added) == (None, b"new")
    del repository.files["package-lock.json"]
    assert await service.ignored_versions(added) == (None, None)
    repository.files["package-lock.json"] = RepositoryFile(
        "package-lock.json", "9" * 40, "120000", b"target"
    )
    with pytest.raises(InvestigationError, match="cannot be summarized"):
        await service.ignored_versions(added)


async def test_a_dependency_change_can_read_the_pinned_runtime_only():
    service, repository, reader, _ = make_service()
    (file,) = reader.scope.files
    reader.scope = reader.scope.model_copy(
        update={
            "files": (
                file.model_copy(
                    update={
                        "old_path": "requirements.txt",
                        "new_path": "requirements.txt",
                    }
                ),
            )
        }
    )
    for name, text in {
        "requirements.txt": b"httpx==1\n",
        ".nvmrc": b"24\n",
        "deploy/Dockerfile": b"FROM python:3.12-slim\n",
        ".github/workflows/ci.yml": b"on: push\n",
    }.items():
        repository.files[name] = RepositoryFile(name, "7" * 40, "100644", text)
    await service.start("head", base="base")
    open_question(service)
    for target in (".nvmrc", "deploy/Dockerfile", ".github/workflows/ci.yml"):
        audit = await service.read(
            request(target=target, relationship="configuration", end_line=1)
        )
        assert audit.action == "read", target
        assert audit.reason == "Runtime configuration for a dependency change"
    assert (await service.read(request(target="store.py"))).action == "denied"
    # Only a configuration read qualifies, so a test link still needs approval.
    tests = await service.read(
        request(target="tests/package.json", relationship="test", end_line=1)
    )
    assert tests.action == "denied"


async def test_a_read_runtime_file_cannot_chain_to_other_runtime_files():
    service, repository, _, _ = make_service()
    for name in ("package.json", ".nvmrc"):
        repository.files[name] = RepositoryFile(name, "7" * 40, "100644", b"{}\n")
    await service.start("head", base="base")
    open_question(service)
    parent = await service.read(request())
    assert parent.action == "read"
    # The parent is an unchanged file, so the dependency-change rule never applies.
    service._snippets[parent.snippet.id] = parent.snippet.model_copy(
        update={"path": "package.json"}
    )
    chained = await service.read(
        request(
            target=".nvmrc",
            relationship="configuration",
            end_line=1,
            parent_read_id=parent.snippet.id,
        )
    )
    assert chained.action == "denied"


async def test_a_code_change_cannot_use_the_runtime_configuration_rule():
    service, repository, _, _ = make_service()
    repository.files[".nvmrc"] = RepositoryFile(".nvmrc", "7" * 40, "100644", b"24\n")
    await service.start("head", base="base")
    open_question(service)
    audit = await service.read(
        request(target=".nvmrc", relationship="configuration", end_line=1)
    )
    assert audit.action == "denied"


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        (
            "from oa.services import store\nstore.load()\n",
            "backend/src/oa/services/store.py",
            True,
        ),
        (
            "from oa.services.store import load\nload()\n",
            "backend/src/oa/services/store.py",
            True,
        ),
        (
            "import oa.services.store as store\nstore.load()\n",
            "backend/src/oa/services/store.py",
            True,
        ),
        # Only folders above the importing file count as roots.
        (
            "from oa.services import store\nstore.load()\n",
            "other/oa/services/store.py",
            False,
        ),
        ("from oa.services import store\n", "backend/src/oa/services/store.py", False),
    ],
)
def test_absolute_imports_resolve_in_a_src_layout(source, target, expected):
    assert (
        verifies_relationship(
            "backend/src/oa/services/sync.py", source, target, "callee", 1, 2
        )
        == expected
    )


async def test_a_change_can_read_another_changed_file():
    service, repository, reader, _ = make_service()
    (file,) = reader.scope.files
    other = file.model_copy(
        update={"old_path": "store.py", "new_path": "store.py", "hunks": ()}
    )
    reader.scope = reader.scope.model_copy(update={"files": (file, other)})
    await service.start("head", base="base")
    open_question(service)
    audit = await service.read(
        request(target="store.py", relationship="shared_interface")
    )
    assert audit.action == "read" and audit.reason == "Changed file"


def test_a_src_layout_test_is_linked_to_the_module_it_imports():
    store = "def load():\n    return 1\n"
    test = "from oa.services.store import load\n\ndef test_load():\n    load()\n"
    assert verifies_relationship(
        "backend/src/oa/services/store.py",
        store,
        "backend/tests/test_store.py",
        "test",
        1,
        2,
        test,
    )
