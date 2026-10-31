import hashlib
import hmac
import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from app.models.github import Receipt
from app.schemas.github import ReviewJob, Trigger
from app.services.ports import JobRepository

REVIEWED_ACTIONS = frozenset({"opened", "reopened", "synchronize"})
# GitHub sends these to every app regardless of its subscriptions.
APP_EVENTS = frozenset({"installation", "installation_repositories"})
COMMAND = re.compile(r"\s*/rush\s+review\s*(?:\n|$)", re.IGNORECASE)
THREAD_COMMAND = re.compile(
    r"\s*/rush\s+(?:explain|accept|dismiss|challenge|learn|approve-learning)"
    r"(?![\w-])",
    re.IGNORECASE,
)
REQUEST_LIMIT = 2000


class GitHubEventService:
    """
    Accept signed GitHub events for approved repositories and store the review
    work they request before GitHub is told the event was received.
    """

    def __init__(
        self,
        jobs: JobRepository,
        secret: bytes,
        repositories: frozenset[str],
        clock: Callable[[], datetime],
        new_id: Callable[[], str],
        wake: Callable[[], None],
    ) -> None:
        self._jobs, self._secret, self._repositories = jobs, secret, repositories
        self._clock, self._new_id, self._wake = clock, new_id, wake

    def authentic(self, body: bytes, signature: str | None) -> bool:
        expected = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        return signature is not None and hmac.compare_digest(
            signature.encode(), f"sha256={expected}".encode()
        )

    async def receive(
        self,
        event: str | None,
        delivery: str | None,
        signature: str | None,
        body: bytes,
    ) -> Receipt:
        if not self.authentic(body, signature):
            return Receipt(401, "The event signature does not match")
        if not event or not delivery:
            return Receipt(400, "The event type and delivery ID are required")
        if event == "ping":
            return Receipt(200, "pong")
        if event in APP_EVENTS:
            return Receipt(200, "Ignored: app installation event")
        if event not in {
            "pull_request",
            "issue_comment",
            "pull_request_review_comment",
        }:
            return Receipt(422, f"Event type {event} is not handled")
        try:
            payload = json.loads(body)
            repository = str(payload["repository"]["full_name"]).lower()
        except (ValueError, KeyError, TypeError):
            return Receipt(400, "The event is not a repository event")
        if repository not in self._repositories:
            return Receipt(403, "The repository is not approved for review")
        return await self._store(
            delivery,
            hashlib.sha256(body).hexdigest(),
            event,
            self._job(event, payload, repository),
        )

    async def _store(
        self, delivery: str, digest: str, event: str, decision: ReviewJob | str
    ) -> Receipt:
        job = None if isinstance(decision, str) else decision
        acceptance = await self._jobs.accept(
            delivery, digest, event, job, self._clock()
        )
        if acceptance.outcome == "duplicate_delivery":
            return Receipt(200, "Repeated delivery ignored")
        if acceptance.outcome == "ignored":
            return Receipt(200, f"Ignored: {decision}")
        if acceptance.outcome == "already_active":
            return Receipt(
                200, "A review of this PR version is already queued", acceptance.job_id
            )
        self._wake()
        return Receipt(202, "Review queued", acceptance.job_id)

    def _job(
        self, event: str, payload: dict[str, Any], repository: str
    ) -> ReviewJob | str:
        try:
            sender = payload["sender"]
            if sender.get("type") == "Bot":
                return "sent by a bot"
            if event == "pull_request_review_comment":
                return self._thread(payload, repository)
            request = (
                self._pull_request(payload)
                if event == "pull_request"
                else self._command(payload)
            )
            if isinstance(request, str):
                return request
            trigger, head, number = request
            now = self._clock()
            return ReviewJob(
                id=self._new_id(),
                repository=repository,
                pull_request=number,
                installation_id=payload["installation"]["id"],
                head_sha=head,
                trigger=trigger,
                requested_by=str(sender["login"]),
                created_at=now,
                updated_at=now,
            )
        except (KeyError, TypeError, AttributeError, ValidationError):
            return "the event is missing PR or installation details"

    def _thread(self, payload: dict[str, Any], repository: str) -> ReviewJob | str:
        comment = payload["comment"]
        if payload["action"] != "created" or not comment.get("in_reply_to_id"):
            return "not a new reply in a review thread"
        if comment["user"].get("type") == "Bot":
            return "sent by a bot"
        body = comment.get("body") or ""
        if not THREAD_COMMAND.match(body):
            return "the reply has no rush command"
        now = self._clock()
        return ReviewJob(
            id=self._new_id(),
            repository=repository,
            pull_request=payload["pull_request"]["number"],
            installation_id=payload["installation"]["id"],
            trigger="thread",
            requested_by=str(comment["user"]["login"]),
            comment_id=comment["in_reply_to_id"],
            request=body.strip()[:REQUEST_LIMIT],
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _pull_request(payload: dict[str, Any]) -> tuple[Trigger, str, int] | str:
        action = payload["action"]
        pull = payload["pull_request"]
        if action not in REVIEWED_ACTIONS:
            return f"PR action {action} does not start a review"
        if pull["state"] != "open":
            return "the PR is closed"
        return action, pull["head"]["sha"], pull["number"]

    @staticmethod
    def _command(payload: dict[str, Any]) -> tuple[Trigger, None, int] | str:
        issue, comment = payload["issue"], payload["comment"]
        if payload["action"] != "created" or "pull_request" not in issue:
            return "not a new PR comment"
        if comment["user"].get("type") == "Bot":
            return "sent by a bot"
        if not COMMAND.match(comment.get("body") or ""):
            return "the comment has no rush command"
        return "command", None, issue["number"]
