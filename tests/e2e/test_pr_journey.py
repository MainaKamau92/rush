"""
The PR review journey on the locally running service, with GitHub and ClickUp
simulated and a scripted stand-in for the Meta model. Everything else is real:
the FastAPI app and worker, SQLite, Git mirrors, change reading, skills, policy,
validation and publication. Set RUSH_JOURNEY_EVIDENCE to a file path to save
the evidence this journey collects.
"""

import asyncio
import hashlib
import hmac
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import dependencies
from app.main import create_app
from app.models.source_access import ToolOutput
from app.services.context_retrieval import ContextRetrievalService
from app.services.source_access import SourceAccessService
from tests.integration.test_code_change_reader import git, run
from tests.integration.test_github_adapter import PRIVATE_KEY
from tests.integration.test_local_review import finding
from tests.unit.test_context_retrieval import Source
from tests.unit.test_model_review import Model

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests/fixtures/customer_lookup"
SECRET = "fictional-journey-secret"  # noqa: S105 (test value)
BOT = "rush-demo[bot]"
DEFECT = "find_customer(connection, external_id)"


class SimulatedGitHub:
    """A stateful stand-in for the GitHub REST API used by the app."""

    def __init__(self):
        self.pulls = {}
        self.comments = {"issue": {}, "review": {}}
        self.checks = {}
        self.next_id = 100
        self.drop_next_post = False
        self.posts = 0

    def pull(self, number, head, base, body=""):
        self.pulls[number] = {"head": head, "base": base, "body": body}

    def _new(self):
        self.next_id += 1
        return self.next_id

    def __call__(self, request):
        path, method = request.url.path, request.method
        if path.endswith("/access_tokens"):
            return httpx.Response(
                201, json={"token": "ghs_journey", "expires_at": "2099-01-01T00:00:00Z"}
            )
        if path == "/app":
            return httpx.Response(200, json={"slug": "rush-demo"})
        rest = path.removeprefix("/repos/lantern/demo/")
        body = json.loads(request.content) if request.content else {}
        for pattern, handler in (
            (r"pulls/(\d+)", self._pull),
            (r"(issues|pulls)/(\d+)/comments", self._thread),
            (r"(issues|pulls)/comments/(\d+)", self._edit),
            (r"commits/(\w+)/check-runs", self._find_checks),
            (r"check-runs(?:/(\d+))?", self._check),
            (r"collaborators/[\w-]+/permission", self._permission),
        ):
            if match := re.fullmatch(pattern, rest):
                return handler(method, match, body, request)
        return httpx.Response(404)

    def _pull(self, method, match, body, request):
        pull = self.pulls[int(match[1])]
        return httpx.Response(
            200,
            json={
                "number": int(match[1]),
                "state": "open",
                "head": {"sha": pull["head"]},
                "base": {
                    "sha": pull["base"],
                    "ref": "main",
                    "repo": {"full_name": "lantern/demo"},
                },
                "body": pull["body"],
            },
        )

    def _thread(self, method, match, body, request):
        kind = "issue" if match[1] == "issues" else "review"
        if method == "GET":
            if int(request.url.params.get("page", "1")) > 1:
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {"id": key, "body": item["body"], "user": {"login": BOT}}
                    for key, item in self.comments[kind].items()
                    if item["pull"] == int(match[2])
                ],
            )
        self.posts += 1
        key = self._new()
        self.comments[kind][key] = {"pull": int(match[2]), **body}
        if self.drop_next_post:
            self.drop_next_post = False
            return httpx.Response(502)
        return httpx.Response(201, json={"id": key})

    def _edit(self, method, match, body, request):
        kind = "issue" if match[1] == "issues" else "review"
        self.comments[kind][int(match[2])]["body"] = body["body"]
        return httpx.Response(200, json={})

    def _find_checks(self, method, match, body, request):
        runs = [
            {"id": key}
            for key, item in self.checks.items()
            if item["head_sha"] == match[1]
        ]
        return httpx.Response(200, json={"check_runs": runs})

    def _check(self, method, match, body, request):
        key = int(match[1]) if match[1] else self._new()
        self.checks[key] = body
        return httpx.Response(201, json={"id": key})

    def _permission(self, method, match, body, request):
        return httpx.Response(200, json={"permission": "write"})

    def findings(self, number):
        return {
            key: item["body"]
            for key, item in self.comments["review"].items()
            if item["pull"] == number
        }

    def summary(self, number):
        (body,) = [
            item["body"]
            for item in self.comments["issue"].values()
            if item["pull"] == number
        ]
        return body

    def check(self, head):
        (check,) = [item for item in self.checks.values() if item["head_sha"] == head]
        return check


class Script:
    """A deterministic stand-in for the Meta model, following the protocol."""

    def __init__(self):
        self.hold = False
        self.holding = False
        self.push = None
        self.ask_unrelated = False

    def __call__(self, request):
        data = json.loads(request.prompt)
        if "candidates" in data:
            return {
                "kind": "critique",
                "verdicts": [
                    {"candidate": index, "verdict": "keep", "reason": "Checked."}
                    for index, _ in enumerate(data["candidates"])
                ],
            }
        if self.hold:
            self.hold, self.holding = False, True
            return asyncio.sleep(3600)
        if self.push is not None:
            push, self.push = self.push, None

            async def after_push():
                await push()
                return self._review(data, request)

            return after_push()
        return self._review(data, request)

    @staticmethod
    def _lines(item, phrase):
        numbers = [
            int(line.split("|", 1)[0])
            for line in item["numbered"].splitlines()
            if phrase in line
        ]
        return {"source_id": item["source_id"], "start": numbers[0], "end": numbers[-1]}

    def _unrelated(self, hunk):
        if not self.ask_unrelated:
            return []
        self.ask_unrelated = False
        return [
            {
                "question_id": "billing",
                "question": "Is billing affected?",
                "origin_hunk_id": hunk["id"],
                "relationship": "callee",
                "target": "billing.py",
                "expected_evidence": "Any billing call from the changed line",
                "start_line": 1,
                "end_line": 5,
            }
        ]

    def _review(self, data, request):
        if "# Team standards" not in (request.instructions or ""):
            return {"kind": "done"}
        hunk = data["change"]["files"][0]["hunks"][0]
        if not any(
            line["kind"] == "added" and DEFECT in line["text"] for line in hunk["lines"]
        ):
            return {"kind": "done"}
        catalog = data["evidence_catalog"]
        store = next(
            (
                item
                for item in catalog
                if item["reference"].startswith("customer_store.py")
            ),
            None,
        )
        if store is None:
            return {
                "kind": "request_context",
                "requests": [
                    *self._unrelated(hunk),
                    {
                        "question_id": "tenant",
                        "question": "Does find_customer keep the tenant boundary?",
                        "origin_hunk_id": hunk["id"],
                        "relationship": "callee",
                        "target": "customer_store.py",
                        "expected_evidence": "The query used when no tenant is given",
                        "start_line": 1,
                        "end_line": 9,
                    },
                ],
            }
        step = finding(request)
        draft = step["findings"][0]
        passages = [
            self._lines(item, phrase)
            for kind, phrase in (("ticket", "tenant"), ("guideline", "tenant ID"))
            for item in catalog
            if item["kind"] == kind
        ]
        draft["evidence"] = [
            *draft["evidence"],
            *passages,
            {"source_id": store["source_id"], "start": 2, "end": 4},
        ]
        step["answers"] = [
            {
                "question_id": "tenant",
                "answer": "Without a tenant the query matches every tenant's row.",
                "evidence_ids": [store["source_id"]],
            },
        ]
        return step


def signed(event, payload, delivery):
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": signature,
    }


def pull_event(action, number, head):
    return {
        "action": action,
        "pull_request": {"number": number, "state": "open", "head": {"sha": head}},
        "repository": {"full_name": "lantern/demo"},
        "installation": {"id": 42},
        "sender": {"login": "nia-moss", "type": "User"},
    }


def wait(client, job_id):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish")


async def build_remote(root):
    unsafe = Path(await run("sh", "scripts/reset-example.sh", "unsafe"))
    safe = Path(await run("sh", "scripts/reset-example.sh", "safe"))
    bare = root / "remote/lantern/demo.git"
    await run("git", "clone", "-q", "--bare", str(unsafe), str(bare))
    await git(
        bare, "fetch", "-q", str(safe), "+refs/tags/fixture-head:refs/tags/safe-head"
    )
    commits = {
        name: await git(bare, "rev-parse", f"{tag}^{{commit}}")
        for name, tag in (
            ("base", "fixture-base"),
            ("unsafe", "fixture-head"),
            ("safe", "safe-head"),
        )
    }
    await git(bare, "update-ref", "refs/heads/main", commits["base"])
    work = root / "work"
    await run("git", "clone", "-q", str(bare), str(work))
    return bare, work, commits


async def push(work, start, number, files, message):
    await git(work, "checkout", "-q", "--detach", start)
    for name, text in files.items():
        (work / name).write_text(text)
        await git(work, "add", name)
    await git(work, "commit", "-q", "-m", message)
    await git(work, "push", "-q", "-f", "origin", f"HEAD:refs/pull/{number}/head")
    return await git(work, "rev-parse", "HEAD")


def test_the_pr_review_journey_on_the_local_service(initialized, tmp_path, monkeypatch):
    evidence = {
        "simulated": "GitHub API and ClickUp MCP are simulated; the Meta model is a "
        "scripted stand-in. The service, worker, SQLite, Git, skills, policy, "
        "validation and publication are real.",
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    bare, work, commits = asyncio.run(build_remote(tmp_path))
    for number, head in ((7, commits["unsafe"]), (8, commits["safe"])):
        asyncio.run(git(bare, "update-ref", f"refs/pull/{number}/head", head))
    github = SimulatedGitHub()
    github.pull(7, commits["unsafe"], commits["base"], "Show customer names. task:CU-7")
    github.pull(8, commits["safe"], commits["base"], "Trim customer names. task:CU-7")
    key = tmp_path / "app-key.pem"
    key.write_text(PRIVATE_KEY)
    settings = initialized.model_copy(
        update={
            "github_app_id": "123",
            "github_private_key_file": key,
            "github_webhook_secret": SecretStr(SECRET),
            "github_repositories": frozenset({"lantern/demo"}),
            "github_api_url": "https://api.github.test",
            "github_git_url": (tmp_path / "remote").as_uri(),
            "review_skills_dir": ROOT / "skills",
            "review_rules_file": CORPUS / "context/rules.json",
            "review_approvers": frozenset({"Ivo Reed"}),
            "review_disclosure": "public",
            "clickup_workspace_id": "w1",
            "approved_tickets": frozenset({"CU-7"}),
            "approved_guidelines": frozenset({"doc/page"}),
        }
    )
    script = Script()
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        dependencies.httpx,
        "AsyncClient",
        lambda **options: original_client(
            transport=httpx.MockTransport(github), **options
        ),
    )

    def model(_settings):
        provider = Model()
        provider.capabilities = provider.capabilities.model_copy(
            update={"adapter_version": "0.2.0"}
        )
        provider.steps = Steps(script)
        return provider

    source = Source(
        {
            "CU-7": ToolOutput((CORPUS / "context/ticket.md").read_text(), False),
            "doc/page": ToolOutput(
                (CORPUS / "context/guideline.md").read_text(), False
            ),
        }
    )
    monkeypatch.setattr(dependencies, "_build_model_provider", model)
    monkeypatch.setattr(
        dependencies,
        "build_context_retrieval",
        lambda _settings: ContextRetrievalService(
            SourceAccessService(
                source,
                {"ticket": frozenset({"CU-7"}), "guideline": frozenset({"doc/page"})},
            ),
            "public",
            lambda: datetime.now(UTC),
        ),
    )
    reads = {}
    reviewer = dependencies.review_pull_request

    async def recording(settings_, job, pull, mirror):
        outcome = await reviewer(settings_, job, pull, mirror)
        reads[job.id] = [
            {
                "path": item.path,
                "action": item.action,
                "reason": item.reason,
                "relationship": item.request.relationship,
                "origin_hunk": item.request.origin_hunk_id,
            }
            for item in outcome.investigation.reads
        ]
        return outcome

    monkeypatch.setattr(dependencies, "review_pull_request", recording)
    deliveries = iter(range(1, 1000))

    def send(client, event, payload):
        body, headers = signed(event, payload, f"delivery-{next(deliveries)}")
        return client.post("/github/webhook", content=body, headers=headers), (
            body,
            headers,
        )

    with TestClient(create_app(settings)) as client:
        # 1. The unsafe PR with its linked ticket.
        response, first = send(
            client, "pull_request", pull_event("opened", 7, commits["unsafe"])
        )
        job = wait(client, response.json()["job"])
        assert job["status"] == "completed", job["reason"]
        ((comment_id, body),) = github.findings(7).items()
        assert "<!-- rush:finding:" in body and "lantern.tenant-lookup@1" in body
        assert "customers.py line 5 (new version)" in body
        assert "Suggested fix:" in body and "Consequence:" in body
        assert github.check(commits["unsafe"])["conclusion"] == "neutral"
        record = asyncio.run(
            dependencies.build_review_records(settings).get(job["run_id"])
        )
        (found,) = record.progress.result.findings
        cited = {item.source_id for item in found.evidence}
        kinds = {
            source.id: source.kind
            for source in (
                *record.inputs.sources,
                *record.progress.result.context_sources,
            )
        }
        assert {"ticket", "guideline", "code"} <= {kinds[item] for item in cited}
        sources = {
            source.id: source
            for source in (
                *record.inputs.sources,
                *record.progress.result.context_sources,
            )
        }
        guideline = next(
            item
            for item in found.evidence
            if sources[item.source_id].kind == "guideline"
        )
        cited_text = sources[guideline.source_id].excerpt.splitlines()[
            guideline.start - 1 : guideline.end
        ]
        assert any("caller's tenant ID" in line for line in cited_text)
        live = [
            {"id": item.id, "kind": item.kind, "reference": item.reference}
            for item in record.inputs.sources
            if item.kind in {"ticket", "guideline"}
        ]
        assert {item["kind"] for item in live} == {"ticket", "guideline"}
        related = reads[job["id"]]
        assert related and all(
            item["reason"] and item["relationship"] for item in related
        )
        assert all(item["path"] != "billing.py" for item in related)
        assert all(
            item.anchor.path != "billing.py" for item in record.progress.result.findings
        )
        summary = github.summary(7)
        assert "No application code or tests were run" in summary
        evidence["initial"] = {
            "pull_request": 7,
            "head": commits["unsafe"],
            "job": job,
            "finding": {
                "rule": f"{found.rule_ref.id}@{found.rule_ref.version}",
                "anchor": found.anchor.model_dump(mode="json"),
                "cited_sources": sorted(cited),
                "problem": found.problem,
                "remediation": found.remediation,
            },
            "live_sources": live,
            "published_comment": body,
            "check": github.check(commits["unsafe"]),
        }
        evidence["context_reads"] = related

        # 2. The safe example has no expected violation.
        response, _ = send(
            client, "pull_request", pull_event("opened", 8, commits["safe"])
        )
        safe = wait(client, response.json()["job"])
        assert github.findings(8) == {}
        assert github.check(commits["safe"])["conclusion"] == "success"
        evidence["safe"] = {"job": safe, "check": github.check(commits["safe"])}

        # 2b. An unrelated read is refused and recorded; the existing defect stays
        # unreported, and the unanswered question keeps the review incomplete.
        asyncio.run(git(bare, "update-ref", "refs/pull/10/head", commits["unsafe"]))
        github.pull(10, commits["unsafe"], commits["base"], "Lookup. task:CU-7")
        script.ask_unrelated = True
        response, _ = send(
            client, "pull_request", pull_event("opened", 10, commits["unsafe"])
        )
        probe = wait(client, response.json()["job"])
        refused = [item for item in reads[probe["id"]] if item["path"] == "billing.py"]
        assert refused and all(item["action"] == "denied" for item in refused)
        assert probe["status"] == "partial"
        probe_record = asyncio.run(
            dependencies.build_review_records(settings).get(probe["run_id"])
        )
        assert all(
            item.anchor.path != "billing.py"
            for item in probe_record.progress.result.findings
        )
        evidence["unrelated_read"] = {
            "job": probe,
            "reads": reads[probe["id"]],
            "limitations": [
                item.code for item in probe_record.progress.result.limitations
            ],
        }

        # 3. The same event again and a rerun command: nothing is duplicated.
        repeated = client.post("/github/webhook", content=first[0], headers=first[1])
        assert repeated.json() == {"message": "Repeated delivery ignored"}
        rerun = {
            "action": "created",
            "issue": {"number": 7, "pull_request": {}},
            "comment": {
                "body": "/rush review",
                "user": {"login": "nia-moss", "type": "User"},
            },
            "repository": {"full_name": "lantern/demo"},
            "installation": {"id": 42},
            "sender": {"login": "nia-moss", "type": "User"},
        }
        # Remove the summary so the rerun has to post one, and lose that response.
        github.comments["issue"] = {
            key: item
            for key, item in github.comments["issue"].items()
            if item["pull"] != 7
        }
        github.drop_next_post = True
        posts = github.posts
        response, _ = send(client, "issue_comment", rerun)
        again = wait(client, response.json()["job"])
        assert again["status"] == "completed"
        assert github.drop_next_post is False and github.posts == posts + 1
        assert list(github.findings(7)) == [comment_id]
        summaries = [c for c in github.comments["issue"].values() if c["pull"] == 7]
        assert len(summaries) == 1
        evidence["repeats"] = {
            "repeated_delivery": repeated.json(),
            "rerun_job": again,
            "inline_comments": len(github.findings(7)),
            "posts_during_rerun": github.posts - posts,
            "summaries_after_lost_response": len(summaries),
        }

        # 4. A fix is pushed: the finding is rechecked and resolved, not duplicated.
        safe_text = (CORPUS / "heads/safe/customers.py").read_text()
        fixed = asyncio.run(
            push(
                work,
                commits["unsafe"],
                7,
                {"customers.py": safe_text},
                "Pass the tenant",
            )
        )
        github.pulls[7]["head"] = fixed
        response, _ = send(client, "pull_request", pull_event("synchronize", 7, fixed))
        corrected = wait(client, response.json()["job"])
        assert corrected["status"] == "completed"
        assert list(github.findings(7)) == [comment_id]
        assert "<!-- rush:resolved -->" in github.findings(7)[comment_id]
        assert github.check(fixed)["conclusion"] == "success"
        evidence["corrected"] = {
            "head": fixed,
            "job": corrected,
            "resolved_comment": comment_id,
            "check": github.check(fixed),
        }

        # 5. A commit arrives during a review: the old result is not published.
        newer = {}

        async def push_during_review():
            head = await push(
                work, commits["unsafe"], 9, {"notes.md": "Follow-up\n"}, "Follow-up"
            )
            github.pulls[9]["head"] = newer["head"] = head

        asyncio.run(git(bare, "update-ref", "refs/pull/9/head", commits["unsafe"]))
        github.pull(9, commits["unsafe"], commits["base"], "Another lookup change")
        shared_check = dict(github.check(commits["unsafe"]))
        script.push = push_during_review
        response, _ = send(
            client, "pull_request", pull_event("opened", 9, commits["unsafe"])
        )
        outdated = wait(client, response.json()["job"])
        assert outdated["status"] == "superseded"
        assert github.findings(9) == {}
        assert not [c for c in github.comments["issue"].values() if c["pull"] == 9]
        assert github.check(commits["unsafe"]) == shared_check
        evidence["push_during_review"] = {"job": outdated, "newer_head": newer["head"]}

        # 6. Restart with an active review and a queued one.
        script.hold = True
        response, _ = send(
            client, "pull_request", pull_event("synchronize", 9, newer["head"])
        )
        active = response.json()["job"]
        deadline = time.monotonic() + 20
        while not script.holding:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert client.get(f"/jobs/{active}").json()["status"] == "running"
        rerun_safe = rerun | {"issue": {"number": 8, "pull_request": {}}}
        response, _ = send(client, "issue_comment", rerun_safe)
        queued = response.json()["job"]
        assert client.get(f"/jobs/{queued}").json()["status"] == "queued"
        interrupted_run = client.get(f"/jobs/{active}").json()["run_id"]

    github.drop_next_post = True
    with TestClient(create_app(settings)) as client:
        recovered = wait(client, active)
        waiting = wait(client, queued)
    records = dependencies.build_review_records(settings)
    interrupted = asyncio.run(records.get(interrupted_run))
    assert interrupted.status in {"failed", "cancelled"}
    assert recovered["attempts"] == 2 and recovered["status"] == "partial"
    final = asyncio.run(records.get(recovered["run_id"]))
    limitations = [item.code for item in final.progress.result.limitations]
    assert "missing_ticket" in limitations
    assert github.drop_next_post is False
    assert waiting["status"] == "completed"
    assert len(github.findings(9)) == 1 and len(github.findings(8)) == 0
    evidence["recovery"] = {
        "interrupted_run": {"id": interrupted_run, "status": interrupted.status},
        "recovered_job": recovered,
        "queued_job": waiting,
        "inline_comments_pr9_after_lost_response": len(github.findings(9)),
        "recovered_limitations": limitations,
    }
    target = os.environ.get("RUSH_JOURNEY_EVIDENCE")
    if target:
        Path(target).write_text(json.dumps(evidence, indent=2, default=str) + "\n")


class Steps(list):
    """An endless step list that asks the shared script for each reply."""

    def __init__(self, script):
        super().__init__([None])
        self.script = script

    def pop(self, index=-1):
        return self.script
