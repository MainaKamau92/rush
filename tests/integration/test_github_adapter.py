import json
import shutil
from datetime import UTC, datetime

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.errors import CodeHostError
from app.internal.adapters.github import GitHubAppAdapter
from app.schemas.github import PullRequest
from tests.integration.test_code_change_reader import git

NOW = datetime(2026, 10, 30, 12, tzinfo=UTC).timestamp()
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_KEY = KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
TOKEN_PATH = "/app/installations/42/access_tokens"  # noqa: S105 (a URL path)


def pull_payload(head="a" * 40, base="c" * 40, **changes):
    return {
        "number": 7,
        "state": "open",
        "head": {"sha": head},
        "base": {"sha": base, "ref": "main", "repo": {"full_name": "Lantern/Demo"}},
        "body": "Fixes the tenant lookup.",
    } | changes


class GitHub:
    def __init__(self):
        self.requests = []
        self.tokens = 0
        self.issued = []
        self.routes = {}

    def __call__(self, request):
        self.requests.append(request)
        if request.url.path == TOKEN_PATH:
            claims = jwt.decode(
                request.headers["authorization"].removeprefix("Bearer "),
                KEY.public_key(),
                algorithms=["RS256"],
                options={"verify_exp": False, "verify_iat": False},
            )
            assert claims["iss"] == "123" and claims["exp"] - claims["iat"] == 600
            self.issued.append(claims["iat"])
            assert json.loads(request.content)["repositories"] in (["demo"], ["gone"])
            self.tokens += 1
            return httpx.Response(
                201,
                json={
                    "token": f"ghs_fictional_{self.tokens}",
                    "expires_at": "2026-10-30T13:00:00Z",
                },
            )
        if request.url.path == "/app":
            return httpx.Response(200, json={"slug": "rush-demo"})
        assert request.headers["authorization"].startswith("Bearer ghs_fictional")
        route = self.routes[request.url.path]
        if isinstance(route, dict):
            route = route[request.method]
        return route(request) if callable(route) else route


def adapter(
    github, *, key=PRIVATE_KEY, git_url="https://github.com", clock=lambda: NOW
):
    client = httpx.AsyncClient(
        base_url="https://api.github.test/", transport=httpx.MockTransport(github)
    )
    return GitHubAppAdapter(client, "123", key, git_url, shutil.which("git"), clock)


async def test_pull_requests_and_permissions_are_read_with_an_installation_token():
    github = GitHub()
    github.routes = {
        "/repos/lantern/demo/pulls/7": httpx.Response(200, json=pull_payload()),
        "/repos/lantern/demo/collaborators/nia-moss/permission": httpx.Response(
            200, json={"permission": "write"}
        ),
        "/repos/lantern/demo/collaborators/ivo/permission": httpx.Response(404),
        "/repos/lantern/demo/collaborators/odd/permission": httpx.Response(
            200, json={"permission": None}
        ),
    }
    host = adapter(github)
    pull = await host.pull_request(42, "lantern/demo", 7)
    assert pull == PullRequest(
        repository="lantern/demo",
        number=7,
        state="open",
        head_sha="a" * 40,
        base_sha="c" * 40,
        base_ref="main",
        body="Fixes the tenant lookup.",
    )
    assert await host.permission(42, "lantern/demo", "nia-moss") == "write"
    assert await host.permission(42, "lantern/demo", "ivo") == "none"
    assert await host.permission(42, "lantern/demo", "odd") == "none"
    assert await host.permission(42, "lantern/demo", "../admin") == "none"
    assert github.tokens == 1
    later = adapter(github, clock=lambda: NOW + 3300)
    later._tokens = host._tokens
    await later.pull_request(42, "lantern/demo", 7)
    assert github.tokens == 2
    assert github.issued == [NOW - 60, NOW + 3240]
    await host.close()


async def test_a_refused_installation_token_is_not_reused():
    github = GitHub()
    github.routes = {"/repos/lantern/demo/pulls/7": httpx.Response(401)}
    host = adapter(github)
    for _ in range(2):
        with pytest.raises(CodeHostError, match="refused access"):
            await host.pull_request(42, "lantern/demo", 7)
    assert github.tokens == 2


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(404), "could not find"),
        (httpx.Response(401), "refused access"),
        (httpx.Response(403), "refused access"),
        (httpx.Response(429), "rate limit"),
        (
            httpx.Response(403, headers={"x-ratelimit-remaining": "0"}),
            "rate limit",
        ),
        (httpx.Response(502), "HTTP 502"),
        (httpx.Response(200, text="<html>"), "not JSON"),
        (httpx.Response(200, json=[1]), "unexpected response"),
        (httpx.Response(200, json=pull_payload(head="short")), "unexpected PR"),
        (httpx.Response(200, json=pull_payload(base=None)), "unexpected PR"),
        (
            httpx.Response(
                200,
                json=pull_payload()
                | {
                    "base": {
                        "sha": "c" * 40,
                        "ref": "main..x",
                        "repo": {"full_name": "a/b"},
                    }
                },
            ),
            "unexpected PR",
        ),
    ],
)
async def test_github_failures_become_safe_messages(response, message):
    github = GitHub()
    github.routes = {"/repos/lantern/demo/pulls/7": response}
    with pytest.raises(CodeHostError, match=message) as error:
        await adapter(github).pull_request(42, "lantern/demo", 7)
    assert "ghs_" not in str(error.value)


async def test_bad_keys_tokens_and_unreachable_github_fail_safely():
    with pytest.raises(CodeHostError, match="private key"):
        await adapter(GitHub(), key="not a key").pull_request(42, "lantern/demo", 7)

    def bad_token(request):
        return httpx.Response(201, json={"token": "ghs_fictional"})

    client = httpx.AsyncClient(
        base_url="https://api.github.test/", transport=httpx.MockTransport(bad_token)
    )
    host = GitHubAppAdapter(client, "123", PRIVATE_KEY, "https://github.com", "git")
    with pytest.raises(CodeHostError, match="token format"):
        await host.pull_request(42, "lantern/demo", 7)

    client = httpx.AsyncClient(
        base_url="https://api.github.test/",
        transport=httpx.MockTransport(lambda request: httpx.Response(404)),
    )
    host = GitHubAppAdapter(client, "123", PRIVATE_KEY, "https://github.com", "git")
    with pytest.raises(CodeHostError, match="not installed for this repository"):
        await host.pull_request(42, "lantern/demo", 7)

    def offline(request):
        raise httpx.ConnectError("private detail")

    client = httpx.AsyncClient(
        base_url="https://api.github.test/", transport=httpx.MockTransport(offline)
    )
    host = GitHubAppAdapter(client, "123", PRIVATE_KEY, "https://github.com", "git")
    with pytest.raises(CodeHostError, match="did not respond") as error:
        await host.pull_request(42, "lantern/demo", 7)
    assert "private detail" not in str(error.value)


async def test_fetch_copies_only_the_pr_versions_into_a_bare_mirror(remote, tmp_path):
    root, head, base = remote
    github = GitHub()
    host = adapter(github, git_url=root.as_uri())
    pull = PullRequest(
        repository="lantern/demo",
        number=7,
        state="open",
        head_sha=head,
        base_sha=base,
        base_ref="main",
    )
    mirror = tmp_path / "state/repositories/lantern__demo.git"
    for _ in range(2):
        await host.fetch(42, pull, mirror)
    assert await git(mirror, "rev-parse", "refs/rush/pull/7/head") == head
    assert await git(mirror, "rev-parse", "refs/rush/pull/7/base") == base
    assert await git(mirror, "rev-parse", "--is-bare-repository") == "true"
    assert not (mirror / "customers.py").exists()
    assert "ghs_" not in (mirror / "config").read_text()
    moved = pull.model_copy(update={"head_sha": "f" * 40})
    with pytest.raises(CodeHostError, match="changed while it was fetched"):
        await host.fetch(42, moved, mirror)
    rewritten = pull.model_copy(update={"base_sha": "e" * 40})
    with pytest.raises(CodeHostError, match="no longer on its target branch"):
        await host.fetch(42, rewritten, mirror)
    missing = pull.model_copy(update={"repository": "lantern/gone"})
    with pytest.raises(CodeHostError, match="could not fetch"):
        await host.fetch(42, missing, mirror)
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    with pytest.raises(CodeHostError, match="local PR mirror"):
        await host.fetch(42, pull, blocked / "lantern__demo.git")
    with pytest.raises(CodeHostError, match="local PR mirror"):
        await host.fetch(42, pull, blocked)


async def test_comments_and_checks_are_read_and_written_as_the_app():
    from app.core.errors import PlacementError, PublicationUncertainError
    from app.models.github import Placement

    def listed(request):
        page = int(request.url.params["page"])
        users = ["rush-demo[bot]", "nia-moss"] * 50 if page == 1 else ["rush-demo[bot]"]
        return httpx.Response(
            200,
            json=[
                {
                    "id": page * 1000 + index,
                    "body": f"c{index}",
                    "user": {"login": user},
                }
                for index, user in enumerate(users)
            ]
            + [{"no": "id"}],
        )

    def review(request):
        line = json.loads(request.content)["line"]
        if line == 999:
            return httpx.Response(422)
        if line == 500:
            return httpx.Response(502)
        return httpx.Response(201, json={"id": 6} if line == 5 else {})

    sent = []

    def recorded(status, payload):
        def respond(request):
            sent.append((request.method, request.url.path, json.loads(request.content)))
            return httpx.Response(status, json=payload)

        return respond

    github = GitHub()
    github.routes = {
        "/repos/lantern/demo/issues/7/comments": {
            "GET": listed,
            "POST": httpx.Response(201, json={"id": 5}),
        },
        "/repos/lantern/demo/pulls/7/comments": {
            "GET": httpx.Response(200, json={"not": "a list"}),
            "POST": review,
        },
        "/repos/lantern/demo/issues/comments/5": recorded(200, {}),
        f"/repos/lantern/demo/commits/{'a' * 40}/check-runs": httpx.Response(
            200, json={"check_runs": [{"id": 9}]}
        ),
        f"/repos/lantern/demo/commits/{'b' * 40}/check-runs": httpx.Response(
            200, json={"check_runs": []}
        ),
        "/repos/lantern/demo/check-runs/9": recorded(200, {}),
        "/repos/lantern/demo/check-runs": recorded(201, {"id": 10}),
    }
    host = adapter(github)
    comments = await host.bot_comments(42, "lantern/demo", 7, "issue")
    assert len(comments) == 51 and comments[-1].id == 2000
    with pytest.raises(CodeHostError, match="comment list"):
        await host.bot_comments(42, "lantern/demo", 7, "review")
    assert await host.post_comment(42, "lantern/demo", 7, "summary", None) == 5
    placed = Placement("a" * 40, "customers.py", 5, "LEFT")
    assert await host.post_comment(42, "lantern/demo", 7, "finding", placed) == 6
    with pytest.raises(PlacementError):
        await host.post_comment(
            42, "lantern/demo", 7, "x", Placement("a" * 40, "a", 999, "RIGHT")
        )
    with pytest.raises(PublicationUncertainError, match="HTTP 502"):
        await host.post_comment(
            42, "lantern/demo", 7, "x", Placement("a" * 40, "a", 500, "RIGHT")
        )
    with pytest.raises(PublicationUncertainError, match="did not confirm"):
        await host.post_comment(
            42, "lantern/demo", 7, "x", Placement("a" * 40, "a", 6, "RIGHT")
        )
    await host.edit_comment(42, "lantern/demo", "issue", 5, "edited")
    await host.report_check(
        42, "lantern/demo", "a" * 40, "neutral", "1 finding", "s" * 70000
    )
    await host.report_check(42, "lantern/demo", "b" * 40, "success", "Clean", "ok")
    assert [(method, path) for method, path, _ in sent] == [
        ("PATCH", "/repos/lantern/demo/issues/comments/5"),
        ("PATCH", "/repos/lantern/demo/check-runs/9"),
        ("POST", "/repos/lantern/demo/check-runs"),
    ]
    assert len(sent[1][2]["output"]["summary"]) == 60000
    assert sent[2][2]["conclusion"] == "success" and sent[2][2]["head_sha"] == "b" * 40
    review_body = json.loads(
        next(
            r
            for r in github.requests
            if r.url.path.endswith("pulls/7/comments") and r.method == "POST"
        ).content
    )
    assert review_body == {
        "body": "finding",
        "commit_id": "a" * 40,
        "path": "customers.py",
        "line": 5,
        "side": "LEFT",
    }

    def no_slug(request):
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(
        base_url="https://api.github.test/", transport=httpx.MockTransport(no_slug)
    )
    nameless = GitHubAppAdapter(client, "123", PRIVATE_KEY, "https://github.com", "git")
    with pytest.raises(CodeHostError, match="app's name"):
        await nameless.bot_comments(42, "lantern/demo", 7, "issue")
