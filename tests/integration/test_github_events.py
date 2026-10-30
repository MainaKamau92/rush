import hashlib
import hmac
import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.errors import ReviewError, StateError
from app.db.repositories.jobs import SQLiteJobRepository
from app.main import create_app
from app.schemas.github import ReviewJob
from app.services.github_events import GitHubEventService

SECRET = b"fictional-webhook-secret"
REPOSITORY = "lantern/demo"
HEAD, NEWER = "a" * 40, "b" * 40
START = datetime(2026, 10, 30, 12, tzinfo=UTC)


def pull_event(action="opened", head=HEAD, state="open", sender="User", **changes):
    return {
        "action": action,
        "pull_request": {"number": 7, "state": state, "head": {"sha": head}},
        "repository": {"full_name": "Lantern/Demo"},
        "installation": {"id": 42},
        "sender": {"login": "nia-moss", "type": sender},
    } | changes


def comment_event(
    body="/rush review\nplease", action="created", on_pull=True, user="User"
):
    issue = {"number": 7} | ({"pull_request": {}} if on_pull else {})
    return {
        "action": action,
        "issue": issue,
        "comment": {"body": body, "user": {"login": "nia-moss", "type": user}},
        "repository": {"full_name": REPOSITORY},
        "installation": {"id": 42},
        "sender": {"login": "nia-moss", "type": "User"},
    }


def signed(payload, secret=SECRET):
    body = json.dumps(payload).encode()
    return body, "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


class Events:
    def __init__(self, database):
        self.jobs = SQLiteJobRepository(database)
        self.ticks = 0
        self.wakes = 0
        self.service = GitHubEventService(
            self.jobs,
            SECRET,
            frozenset({REPOSITORY}),
            self.clock,
            lambda: f"job-{self.ticks}",
            self.wake,
        )

    def clock(self):
        self.ticks += 1
        return START + timedelta(seconds=self.ticks)

    def wake(self):
        self.wakes += 1

    async def send(self, event, payload, delivery="d-1", secret=SECRET):
        body, signature = signed(payload, secret)
        return await self.service.receive(event, delivery, signature, body)


@pytest.fixture
def events(initialized):
    return Events(initialized.database_path)


async def test_only_signed_events_for_approved_repositories_are_accepted(events):
    body, signature = signed(pull_event())
    receive = events.service.receive
    assert (await receive("pull_request", "d", None, body)).status_code == 401
    assert (
        await receive("pull_request", "d", signature, body + b" ")
    ).status_code == 401
    forged = await events.send("pull_request", pull_event(), secret=b"guess")
    assert (forged.status_code, forged.message) == (
        401,
        "The event signature does not match",
    )
    assert (await receive("pull_request", None, signature, body)).status_code == 400
    assert (await events.send("ping", {"zen": "Keep it simple."})).message == "pong"
    push = await events.send("push", pull_event())
    assert (push.status_code, push.message) == (422, "Event type push is not handled")
    assert (await events.send("pull_request", {"zen": 1})).status_code == 400
    other = pull_event(repository={"full_name": "lantern/other"})
    refused = await events.send("pull_request", other)
    assert (refused.status_code, refused.message) == (
        403,
        "The repository is not approved for review",
    )
    installed = await events.send("installation", {"action": "created"})
    assert (installed.status_code, installed.message) == (
        200,
        "Ignored: app installation event",
    )
    assert await events.jobs.recent(10) == ()
    assert events.wakes == 0


async def test_pull_requests_queue_one_job_per_version_and_ignore_repeats(events):
    opened = await events.send("pull_request", pull_event(), "d-1")
    assert (opened.status_code, opened.message) == (202, "Review queued")
    assert events.wakes == 1
    job = await events.jobs.get(opened.job_id)
    assert (job.repository, job.pull_request, job.head_sha, job.trigger) == (
        REPOSITORY,
        7,
        HEAD,
        "opened",
    )
    assert (job.installation_id, job.requested_by, job.status) == (
        42,
        "nia-moss",
        "queued",
    )
    repeated = await events.send("pull_request", pull_event(), "d-1")
    assert (repeated.status_code, repeated.message) == (
        200,
        "Repeated delivery ignored",
    )
    replayed = await events.send("pull_request", pull_event(), "d-replayed")
    assert replayed.message == "Repeated delivery ignored"
    again = await events.send("pull_request", pull_event("reopened"), "d-2")
    assert (again.status_code, again.job_id) == (200, opened.job_id)
    assert again.message == "A review of this PR version is already queued"
    newer = await events.send("pull_request", pull_event("synchronize", NEWER), "d-3")
    assert newer.status_code == 202 and newer.job_id != opened.job_id
    superseded = await events.jobs.get(opened.job_id)
    assert superseded.status == "superseded"
    assert superseded.reason == "A newer commit arrived before this review started"
    assert [item.id for item in await events.jobs.recent(10)] == [
        newer.job_id,
        opened.job_id,
    ]
    assert events.wakes == 2


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (pull_event("closed"), "PR action closed does not start a review"),
        (pull_event("synchronize", state="closed"), "the PR is closed"),
        (pull_event(sender="Bot"), "sent by a bot"),
        (pull_event(installation=None), "the event is missing PR or installation"),
        (pull_event(pull_request={"number": 0}), "the event is missing PR"),
    ],
)
async def test_unreviewed_pull_request_events_are_ignored_with_a_reason(
    events, payload, reason
):
    receipt = await events.send("pull_request", payload)
    assert receipt.status_code == 200 and receipt.message.startswith(
        f"Ignored: {reason}"
    )
    assert await events.jobs.recent(10) == ()
    repeated = await events.send("pull_request", payload)
    assert repeated.message == "Repeated delivery ignored"


async def test_rerun_commands_come_only_from_people_commenting_on_prs(events):
    for payload, reason in [
        (comment_event(on_pull=False), "not a new PR comment"),
        (comment_event(action="edited"), "not a new PR comment"),
        (comment_event(user="Bot"), "sent by a bot"),
        (comment_event("Looks fine; /rush review"), "the comment has no rush command"),
        (comment_event(body=None), "the comment has no rush command"),
    ]:
        receipt = await events.send("issue_comment", payload, f"d-{reason}-{payload}")
        assert receipt.message == f"Ignored: {reason}"
    command = await events.send("issue_comment", comment_event(" /RUSH  Review "))
    assert command.status_code == 202
    job = await events.jobs.get(command.job_id)
    assert (job.trigger, job.head_sha, job.requested_by) == (
        "command",
        None,
        "nia-moss",
    )
    replayed = await events.send("issue_comment", comment_event(" /RUSH  Review "))
    assert replayed.message == "Repeated delivery ignored"
    duplicate = await events.send("issue_comment", comment_event(), "d-2")
    assert (duplicate.status_code, duplicate.job_id) == (200, command.job_id)
    pushed = await events.send("pull_request", pull_event("synchronize"), "d-3")
    assert pushed.status_code == 202
    assert (await events.jobs.get(command.job_id)).status == "superseded"


def job(job_id, head=HEAD, number=7, at=START):
    return ReviewJob(
        id=job_id,
        repository=REPOSITORY,
        pull_request=number,
        installation_id=42,
        head_sha=head,
        trigger="opened",
        requested_by="nia-moss",
        created_at=at,
        updated_at=at,
    )


async def test_jobs_are_claimed_in_order_and_recovered_after_a_stop(initialized):
    jobs = SQLiteJobRepository(initialized.database_path)
    later = START + timedelta(minutes=1)
    await jobs.accept("d-1", "sha-1", "pull_request", job("job-1"), START)
    await jobs.accept(
        "d-2", "sha-2", "pull_request", job("job-2", number=8, at=later), later
    )
    claimed = await jobs.claim(later)
    assert (claimed.id, claimed.status, claimed.attempts, claimed.run_id) == (
        "job-1",
        "running",
        1,
        "job-1-1",
    )
    running = await jobs.accept(
        "d-3", "sha-3", "pull_request", job("job-3", at=later), later
    )
    assert (running.outcome, running.job_id) == ("already_active", "job-1")
    await jobs.note("job-1", "Fetching the PR versions", later)
    assert (await jobs.get("job-1")).reason == "Fetching the PR versions"
    recovered = await jobs.recover(later, 3)
    assert [(item.id, item.status) for item in recovered] == [("job-1", "queued")]
    assert recovered[0].reason == "The service stopped during this review; queued again"
    for attempt in (2, 3):
        claimed = await jobs.claim(later)
        assert (claimed.id, claimed.run_id) == ("job-1", f"job-1-{attempt}")
        recovered = await jobs.recover(later, 3)
    assert recovered[0].status == "failed"
    assert "not retried" in recovered[0].reason
    second = await jobs.claim(later)
    assert second.id == "job-2" and await jobs.claim(later) is None
    await jobs.finish("job-2", "completed", "Review complete", later)
    finished = await jobs.get("job-2")
    assert (finished.status, finished.reason) == ("completed", "Review complete")
    with pytest.raises(ReviewError, match="running"):
        await jobs.finish("job-2", "failed", "again", later)
    with pytest.raises(ReviewError, match="not found"):
        await jobs.get("job-404")
    with sqlite3.connect(initialized.database_path) as connection:
        connection.execute("UPDATE review_jobs SET created_at = 'never'")
    with pytest.raises(StateError, match="invalid"):
        await jobs.recent(5)


def test_webhook_and_job_routes_need_github_configuration(initialized):
    with TestClient(create_app(initialized)) as client:
        assert client.post("/github/webhook").status_code == 404
        response = client.get("/jobs")
    assert response.json() == {"detail": "GitHub reviews are not configured"}


async def test_recovery_supersedes_an_interrupted_job_with_a_newer_request(
    initialized,
):
    jobs = SQLiteJobRepository(initialized.database_path)
    later = START + timedelta(minutes=1)
    command = job("job-command", head=None).model_copy(update={"trigger": "command"})
    await jobs.accept("d-1", "sha-1", "issue_comment", command, START)
    await jobs.claim(START)
    pushed = job("job-pushed", head=NEWER, at=later)
    await jobs.accept("d-2", "sha-2", "pull_request", pushed, later)
    (recovered,) = await jobs.recover(later, 3)
    assert recovered.id == "job-command"
    interrupted = await jobs.get("job-command")
    assert interrupted.status == "superseded"
    assert interrupted.reason.startswith("A newer review of this PR was requested")
    assert (await jobs.get("job-pushed")).status == "queued"
    assert (await jobs.claim(later)).id == "job-pushed"
