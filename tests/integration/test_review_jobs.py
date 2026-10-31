import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import dependencies
from app.core.errors import (
    ChangeError,
    CodeHostError,
    ModelError,
    PublicationUncertainError,
    ReviewError,
    StateError,
)
from app.db.repositories.jobs import SQLiteJobRepository
from app.db.repositories.reviews import SQLiteReviewRepository
from app.main import create_app
from app.models.github import HostComment
from app.provider.github.abstract import CodeHostAbstract
from app.schemas.github import PullRequest
from app.schemas.investigation import InvestigationReport
from app.schemas.local_review import ReviewOutcome
from app.services.review_jobs import ReviewJobService, mirror_name
from app.services.review_records import ReviewRecordService
from tests.integration.test_github_adapter import PRIVATE_KEY, GitHub, pull_payload
from tests.integration.test_github_events import (
    HEAD,
    REPOSITORY,
    SECRET,
    job,
    pull_event,
    signed,
)
from tests.unit.test_model_review import Model

ROOT = Path(__file__).resolve().parents[2]
NOTHING_READ = InvestigationReport(
    scope=None, questions=(), reads=(), counters=(), elapsed_seconds=0, limitations=()
)
START = datetime(2026, 10, 30, 12, tzinfo=UTC)
PULL = PullRequest(
    repository=REPOSITORY,
    number=7,
    state="open",
    head_sha=HEAD,
    base_sha="c" * 40,
    base_ref="main",
)


class Host(CodeHostAbstract):
    def __init__(self):
        self.pull = PULL
        self.permissions = {}
        self.fetched = []
        self.error = None
        self.closed = False

    async def pull_request(self, installation_id, repository, number):
        if self.error is not None:
            raise self.error
        return self.pull

    async def permission(self, installation_id, repository, user):
        return self.permissions.get(user, "read")

    async def fetch(self, installation_id, pull, mirror):
        self.fetched.append((pull.head_sha, mirror))

    async def close(self):
        self.closed = True

    # Publication: comments[kind] maps comment IDs to the app's comment bodies.
    comments = None
    checks = None
    post_errors = None
    edit_error = None

    def _state(self):
        if self.comments is None:
            self.comments = {"issue": {}, "review": {}}
            self.checks, self.post_errors, self.placements = [], [], []

    async def bot_comments(self, installation_id, repository, number, kind):
        self._state()
        return [HostComment(key, body) for key, body in self.comments[kind].items()]

    async def post_comment(self, installation_id, repository, number, body, placement):
        self._state()
        kind = "issue" if placement is None else "review"
        error = self.post_errors.pop(0) if self.post_errors else None
        if isinstance(error, PublicationUncertainError) and error.args[0] == "saved":
            self.comments[kind][len(self.comments[kind]) + 100] = body
        if error is not None:
            raise error
        key = len(self.comments["issue"]) + len(self.comments["review"]) + 1
        self.comments[kind][key] = body
        self.placements.append(placement)
        return key

    async def edit_comment(self, installation_id, repository, kind, comment_id, body):
        self._state()
        if self.edit_error is not None:
            raise self.edit_error
        self.comments[kind][comment_id] = body

    async def report_check(
        self, installation_id, repository, head_sha, conclusion, title, summary
    ):
        self._state()
        self.checks.append((head_sha, conclusion, title))


class Worker:
    def __init__(self, settings, inputs):
        self.jobs = SQLiteJobRepository(settings.database_path)
        self.records = ReviewRecordService(
            SQLiteReviewRepository(settings.database_path), self.clock
        )
        self.host = Host()
        self.inputs = inputs
        self.outcome = ("skipped", "No approved skill matches the changed files")
        self.failure = None
        self.moved = None
        self.ticks = 0
        self.mirrors = settings.mirrors_dir
        self.service = ReviewJobService(
            self.jobs,
            self.host,
            self.review,
            self.records,
            self.mirrors,
            self.clock,
            poll_seconds=0.01,
        )

    def clock(self):
        self.ticks += 1
        return START + timedelta(seconds=self.ticks)

    async def review(self, queued, pull, mirror):
        await self.records.create(queued.run_id, self.inputs)
        if self.failure is not None:
            raise self.failure
        record = await self.records.advance(queued.run_id, *self.outcome)
        if self.moved is not None:
            self.host.pull = self.host.pull.model_copy(update={"head_sha": self.moved})
        return ReviewOutcome(record=record, investigation=NOTHING_READ)

    async def queue(self, trigger="opened", head=HEAD):
        queued = job(f"job-{trigger}", head=head).model_copy(
            update={"trigger": trigger}
        )
        await self.jobs.accept(
            f"d-{queued.id}", f"sha-{queued.id}", "pull_request", queued, START
        )
        return queued.id


@pytest.fixture
def worker(initialized, review_inputs):
    return Worker(initialized, review_inputs)


async def test_a_queued_pull_request_is_fetched_reviewed_and_recorded(worker):
    job_id = await worker.queue()
    assert await worker.service.run_once()
    finished = await worker.service.get(job_id)
    assert (finished.status, finished.reason, finished.run_id) == (
        "skipped",
        "No approved skill matches the changed files",
        f"{job_id}-1",
    )
    assert worker.host.fetched == [(HEAD, worker.mirrors / "lantern__demo.git")]
    assert (await worker.records.get(finished.run_id)).status == "skipped"
    assert not await worker.service.run_once()
    assert [item.id for item in await worker.service.recent(5)] == [job_id]
    assert mirror_name("lantern/demo") == "lantern__demo.git"


@pytest.mark.parametrize(
    ("pull", "trigger", "status", "reason"),
    [
        (PULL.model_copy(update={"state": "closed"}), "opened", "skipped", "closed"),
        (
            PULL.model_copy(update={"repository": "lantern/other"}),
            "opened",
            "skipped",
            "different repository",
        ),
        (
            PULL.model_copy(update={"head_sha": "b" * 40}),
            "synchronize",
            "superseded",
            "newer commit",
        ),
        (PULL, "command", "skipped", "nia-moss asked for a review but does not"),
    ],
)
async def test_ineligible_jobs_are_skipped_with_a_reason(
    worker, pull, trigger, status, reason
):
    worker.host.pull = pull
    job_id = await worker.queue(trigger=trigger)
    await worker.service.run_once()
    finished = await worker.service.get(job_id)
    assert finished.status == status and reason in finished.reason
    assert worker.host.fetched == []


async def test_a_rerun_needs_the_senders_current_write_access(worker):
    worker.host.permissions["nia-moss"] = "maintain"
    worker.outcome = ("failed", "The model stage failed")
    job_id = await worker.queue(trigger="command", head=None)
    await worker.service.run_once()
    finished = await worker.service.get(job_id)
    assert (finished.status, finished.reason) == ("failed", "The model stage failed")
    assert worker.host.fetched == [(HEAD, worker.mirrors / "lantern__demo.git")]


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (CodeHostError("GitHub refused access"), "GitHub refused access"),
        (ChangeError("Git could not list"), "Git could not list"),
        (
            RuntimeError("private detail"),
            "Unexpected RuntimeError; see the service log",
        ),
    ],
)
async def test_failures_are_recorded_without_stopping_the_worker(worker, error, reason):
    worker.host.error = error
    job_id = await worker.queue()
    assert await worker.service.run_once()
    finished = await worker.service.get(job_id)
    assert (finished.status, finished.reason) == ("failed", reason)


async def test_a_failure_during_review_closes_the_run_record(worker):
    worker.failure = ModelError("Set META_AI_KEY before checking model access")
    job_id = await worker.queue()
    await worker.service.run_once()
    finished = await worker.service.get(job_id)
    assert finished.status == "failed" and "META_AI_KEY" in finished.reason
    record = await worker.records.get(finished.run_id)
    assert (
        record.status == "failed" and "META_AI_KEY" in record.progress.events[-1].reason
    )


async def test_restart_requeues_interrupted_work_once_and_closes_its_run(worker):
    job_id = await worker.queue()
    claimed = await worker.jobs.claim(START)
    await worker.records.create(claimed.run_id, worker.inputs)
    (recovered,) = await worker.service.recover()
    assert recovered.status == "queued"
    interrupted = await worker.records.get(claimed.run_id)
    assert interrupted.status == "failed"
    assert interrupted.progress.events[-1].reason == (
        "The service stopped during this review"
    )
    await worker.service.run_once()
    finished = await worker.service.get(job_id)
    assert (finished.status, finished.run_id) == ("skipped", f"{job_id}-2")
    assert len(worker.host.fetched) == 1


async def test_the_worker_loop_survives_failures_and_requeues_its_own_job(
    worker, monkeypatch
):
    recover, finish = worker.jobs.recover, worker.jobs.finish
    calls = {"recover": 0, "finish": 0}

    async def flaky_recover(at, max_attempts):
        calls["recover"] += 1
        if calls["recover"] == 1:
            raise StateError("Cannot access review jobs")
        return await recover(at, max_attempts)

    async def flaky_finish(job_id, status, reason, at):
        calls["finish"] += 1
        if calls["finish"] == 1:
            raise ReviewError("Only a running review job can finish")
        return await finish(job_id, status, reason, at)

    monkeypatch.setattr(worker.jobs, "recover", flaky_recover)
    monkeypatch.setattr(worker.jobs, "finish", flaky_finish)
    job_id = await worker.queue()
    task = asyncio.create_task(worker.service.run())
    for _ in range(300):
        if (await worker.service.get(job_id)).status == "skipped":
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    finished = await worker.service.get(job_id)
    assert (finished.status, finished.attempts) == ("skipped", 2)
    assert calls == {"recover": 3, "finish": 2}
    await worker.service.close()
    assert worker.host.closed


def github_settings(initialized, tmp_path, root):
    key = tmp_path / "app-key.pem"
    key.write_text(PRIVATE_KEY)
    return initialized.model_copy(
        update={
            "github_app_id": "123",
            "github_private_key_file": key,
            "github_webhook_secret": SecretStr(SECRET.decode()),
            "github_repositories": frozenset({REPOSITORY}),
            "github_api_url": "https://api.github.test",
            "github_git_url": root.as_uri(),
            "review_skills_dir": ROOT / "skills",
            "review_rules_file": ROOT
            / "tests/fixtures/customer_lookup/context/rules.json",
            "review_approvers": frozenset({"Ivo Reed"}),
            "review_disclosure": "public",
        }
    )


def wait(client, job_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        found = client.get(f"/jobs/{job_id}").json()
        if found["status"] not in {"queued", "running"}:
            return found
        time.sleep(0.05)
    raise AssertionError("The review job did not finish")


def test_a_signed_pull_request_event_is_reviewed_by_the_local_service(
    initialized, tmp_path, remote, monkeypatch
):
    root, head, base = remote
    settings = github_settings(initialized, tmp_path, root)
    github = GitHub()
    github.routes = {
        "/repos/lantern/demo/pulls/7": httpx.Response(
            200, json=pull_payload(head, base)
        ),
        "/repos/lantern/demo/issues/7/comments": {
            "GET": httpx.Response(200, json=[]),
            "POST": httpx.Response(201, json={"id": 11}),
        },
        "/repos/lantern/demo/pulls/7/comments": {
            "GET": httpx.Response(200, json=[]),
            "POST": httpx.Response(201, json={"id": 12}),
        },
        f"/repos/lantern/demo/commits/{head}/check-runs": httpx.Response(
            200, json={"check_runs": []}
        ),
        "/repos/lantern/demo/check-runs": httpx.Response(201, json={"id": 13}),
    }
    original = httpx.AsyncClient
    monkeypatch.setattr(
        dependencies.httpx,
        "AsyncClient",
        lambda **options: original(transport=httpx.MockTransport(github), **options),
    )

    def model(_settings):
        provider = Model()
        provider.capabilities = provider.capabilities.model_copy(
            update={"adapter_version": "0.2.0"}
        )
        provider.steps = [{"kind": "done"}] * 3
        return provider

    monkeypatch.setattr(dependencies, "_build_model_provider", model)
    body, signature = signed(pull_event(head=head))
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": "delivery-1",
        "X-Hub-Signature-256": signature,
    }
    with TestClient(create_app(settings)) as client:
        accepted = client.post("/github/webhook", content=body, headers=headers)
        assert accepted.status_code == 202
        job_id = accepted.json()["job"]
        finished = wait(client, job_id)
        repeated = client.post("/github/webhook", content=body, headers=headers)
        assert repeated.json() == {"message": "Repeated delivery ignored"}
        forged = client.post("/github/webhook", content=body + b" ", headers=headers)
        assert forged.status_code == 401
        assert forged.json() == {"detail": "The event signature does not match"}
        listed = client.get("/jobs", params={"limit": 5}).json()
        assert [item["id"] for item in listed] == [job_id]
        assert client.get("/jobs/job-missing").status_code == 404
    assert finished["status"] in {"completed", "partial"}, finished["reason"]
    records = ReviewRecordService(
        SQLiteReviewRepository(settings.database_path), lambda: START
    )
    record = asyncio.run(records.get(finished["run_id"]))
    assert (record.inputs.repository, record.inputs.pull_request) == (REPOSITORY, 7)
    assert (record.inputs.head_sha, record.inputs.target_sha) == (head, base)
    assert record.status == finished["status"]
    assert [pin.id for pin in record.inputs.rules] == ["lantern.tenant-lookup"]
    mirror = settings.mirrors_dir / "lantern__demo.git"
    assert not (mirror / "customers.py").exists()
    assert "Published on the PR" in finished["reason"]
    posted = {
        (request.method, request.url.path): request
        for request in github.requests
        if request.method in {"POST", "PATCH"}
    }
    summary = json.loads(
        posted[("POST", "/repos/lantern/demo/issues/7/comments")].content
    )
    assert summary["body"].startswith("<!-- rush:summary -->")
    check = json.loads(posted[("POST", "/repos/lantern/demo/check-runs")].content)
    assert (check["name"], check["head_sha"], check["status"]) == (
        "rush review",
        head,
        "completed",
    )
    assert check["conclusion"] == (
        "success" if record.status == "completed" else "neutral"
    )
    serialized = json.dumps(listed)
    assert "ghs_" not in serialized and SECRET.decode() not in serialized


async def test_github_reviews_need_complete_trusted_configuration(
    initialized, tmp_path, monkeypatch
):
    with pytest.raises(CodeHostError, match="GitHub App ID"):
        dependencies.build_github_reviews(initialized)
    settings = github_settings(initialized, tmp_path, tmp_path)
    missing = settings.model_copy(
        update={"github_private_key_file": tmp_path / "missing.pem"}
    )
    with pytest.raises(CodeHostError, match="private key file"):
        dependencies.build_github_reviews(missing)
    monkeypatch.setattr(dependencies.shutil, "which", lambda name: None)
    with pytest.raises(ChangeError, match="Git is not installed"):
        dependencies.build_github_reviews(settings)
    queued = job("job-1").model_copy(update={"run_id": "job-1-1"})
    unset = settings.model_copy(update={"review_skills_dir": None})
    with pytest.raises(ReviewError, match="RUSH_REVIEW_SKILLS_DIR"):
        await dependencies.review_pull_request(unset, queued, PULL, tmp_path)
    unreadable = settings.model_copy(update={"review_rules_file": tmp_path})
    with pytest.raises(ReviewError, match="approved policy file"):
        dependencies._trusted_text(unreadable.review_rules_file)
    assert dependencies._trusted_text(None) is None


def test_the_cli_lists_recent_jobs(initialized, monkeypatch, capsys):
    from tests.e2e.test_setup_cli import invoke

    monkeypatch.setenv("RUSH_STATE_DIR", str(initialized.state_dir))
    queued = job("job-cli")
    asyncio.run(
        SQLiteJobRepository(initialized.database_path).accept(
            "d-cli", "sha-cli", "pull_request", queued, START
        )
    )
    assert invoke(monkeypatch, "jobs", "--limit", "5") == 0
    listed = json.loads(capsys.readouterr().out)["jobs"]
    assert [(item["id"], item["status"]) for item in listed] == [("job-cli", "queued")]


def publishing(worker):
    from app.db.repositories.publications import SQLitePublicationRepository
    from app.services.pull_request_publication import PullRequestPublisher

    worker.host._state()
    worker.inputs = worker.inputs.model_copy(update={"head_sha": HEAD})
    return ReviewJobService(
        worker.jobs,
        worker.host,
        worker.review,
        worker.records,
        worker.mirrors,
        worker.clock,
        publisher=PullRequestPublisher(
            worker.host,
            SQLitePublicationRepository(worker.mirrors.parent / "rush.sqlite3"),
            worker.clock,
        ),
    )


async def test_only_the_current_pr_version_receives_the_published_result(worker):
    service = publishing(worker)
    job_id = await worker.queue()
    await service.run_once()
    finished = await service.get(job_id)
    assert finished.status == "skipped"
    assert finished.reason.endswith(
        "Published on the PR: Not reviewed: No approved skill matches the changed files"
    )
    assert worker.host.checks[-1][1] == "neutral"
    worker.moved = "b" * 40
    second = await worker.queue(trigger="reopened")
    worker.host.pull = PULL
    await service.run_once()
    outdated = await service.get(second)
    assert (outdated.status, outdated.reason) == (
        "superseded",
        "A newer commit arrived; this result was not published",
    )
    assert len(worker.host.checks) == 1


async def test_publication_and_execution_failures_are_reported(worker):
    service = publishing(worker)
    worker.host.post_errors = [CodeHostError("GitHub returned HTTP 403")] * 2
    job_id = await worker.queue()
    await service.run_once()
    finished = await service.get(job_id)
    assert (finished.status, finished.reason) == (
        "failed",
        "Reviewed, but publishing failed: GitHub returned HTTP 403",
    )
    worker.host.post_errors = []
    worker.failure = ModelError("Set META_AI_KEY before checking model access")
    failed = await worker.queue(trigger="synchronize", head=HEAD)
    await service.run_once()
    assert (await service.get(failed)).status == "failed"
    assert worker.host.checks[-1] == (HEAD, "failure", "Review could not run")


async def test_failure_reports_skip_moved_heads_and_publication_state_errors(
    worker, monkeypatch
):
    service = publishing(worker)
    worker.failure = ModelError("Model stage failed")
    calls = []
    original = worker.host.pull_request

    async def moving(installation_id, repository, number):
        calls.append(number)
        if len(calls) == 2:
            return PULL.model_copy(update={"head_sha": "b" * 40})
        if len(calls) == 4:
            raise CodeHostError("GitHub did not respond")
        return await original(installation_id, repository, number)

    monkeypatch.setattr(worker.host, "pull_request", moving)
    first = await worker.queue()
    await service.run_once()
    second = await worker.queue(trigger="reopened")
    await service.run_once()
    assert [(await service.get(item)).status for item in (first, second)] == [
        "failed",
        "failed",
    ]
    assert worker.host.checks == []
    worker.failure = None
    monkeypatch.setattr(worker.host, "pull_request", original)

    async def broken(*args):
        raise StateError("Cannot access publications")

    monkeypatch.setattr(service._publisher._store, "plan", broken)
    third = await worker.queue(trigger="synchronize")
    await service.run_once()
    finished = await service.get(third)
    assert (finished.status, finished.reason) == (
        "failed",
        "Reviewed, but publishing failed: Cannot access publications",
    )
