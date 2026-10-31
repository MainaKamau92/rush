import base64
import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt
from pydantic import ValidationError

from app.core.errors import CodeHostError, PlacementError, PublicationUncertainError
from app.internal.adapters.git import SAFE_OPTIONS, run_git, safe_environment
from app.models.github import HostComment, Placement
from app.provider.github.abstract import CodeHostAbstract, CommentKind
from app.schemas.github import PullRequest

TOKEN_MARGIN_SECONDS = 300
FETCH_TIMEOUT_SECONDS = 180
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
CHECK_NAME = "rush review"
MAX_PAGES = 10
CHECK_TEXT_LIMIT = 60000


class GitHubAppAdapter(CodeHostAbstract):
    """
    Read PRs as a GitHub App installation and copy their commits into a bare
    mirror. Tokens stay in memory and reach Git only through its environment.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        app_id: str,
        private_key: str,
        git_url: str,
        executable: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client, self._app_id, self._private_key = client, app_id, private_key
        self._git_url, self._executable, self._clock = git_url, executable, clock
        self._tokens: dict[tuple[int, str], tuple[str, float]] = {}
        self._login: str | None = None

    async def pull_request(
        self, installation_id: int, repository: str, number: int
    ) -> PullRequest:
        token = await self._token(installation_id, repository)
        data = await self._json(
            "GET",
            f"repos/{repository}/pulls/{number}",
            token,
            missing="GitHub could not find the repository or PR",
        )
        try:
            return PullRequest(
                repository=str(data["base"]["repo"]["full_name"]).lower(),
                number=data["number"],
                state=data["state"],
                head_sha=data["head"]["sha"],
                base_sha=data["base"]["sha"],
                base_ref=data["base"]["ref"],
                body=data.get("body"),
            )
        except (KeyError, TypeError, ValidationError) as error:
            raise CodeHostError("GitHub returned an unexpected PR format") from error

    async def permission(self, installation_id: int, repository: str, user: str) -> str:
        if not LOGIN.fullmatch(user):
            return "none"
        token = await self._token(installation_id, repository)
        response = await self._send(
            "GET", f"repos/{repository}/collaborators/{user}/permission", token
        )
        if response.status_code == 404:
            return "none"
        permission = _payload(self._checked(response)).get("permission")
        return permission if isinstance(permission, str) else "none"

    async def fetch(
        self, installation_id: int, pull: PullRequest, mirror: Path
    ) -> None:
        token = await self._token(installation_id, pull.repository)
        environment = safe_environment()
        if not (mirror / "HEAD").is_file():
            await self._create(mirror, environment)
        credential = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        number = pull.number
        code, _ = await self._mirror(
            mirror,
            environment
            | {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.extraHeader",
                "GIT_CONFIG_VALUE_0": f"Authorization: Basic {credential}",
            },
            "-c",
            f"protocol.{urlsplit(self._git_url).scheme}.allow=always",
            "-c",
            "credential.helper=",
            "-c",
            "http.followRedirects=false",
            "fetch",
            "--no-tags",
            "--no-recurse-submodules",
            "--no-write-fetch-head",
            "--quiet",
            f"{self._git_url}/{pull.repository}.git",
            f"+refs/pull/{number}/head:refs/rush/pull/{number}/head",
            f"+refs/heads/{pull.base_ref}:refs/rush/pull/{number}/base",
        )
        if code != 0:
            raise CodeHostError("Git could not fetch the PR versions from GitHub")
        missing = {
            pull.head_sha: "The PR changed while it was fetched; the newer version "
            "is reviewed by its own event",
            pull.base_sha: "The PR's target commit is no longer on its target "
            "branch; update the PR, then comment /rush review",
        }
        for commit, reason in missing.items():
            code, _ = await self._mirror(
                mirror, environment, "cat-file", "-e", f"{commit}^{{commit}}"
            )
            if code != 0:
                raise CodeHostError(reason)

    async def bot_comments(
        self, installation_id: int, repository: str, number: int, kind: CommentKind
    ) -> list[HostComment]:
        login = await self._app_login()
        token = await self._token(installation_id, repository)
        area = "issues" if kind == "issue" else "pulls"
        found: list[HostComment] = []
        for page in range(1, MAX_PAGES + 1):
            response = self._checked(
                await self._send(
                    "GET",
                    f"repos/{repository}/{area}/{number}/comments",
                    token,
                    params={"per_page": 100, "page": page},
                )
            )
            items = _items(response)
            found += [
                HostComment(int(item["id"]), str(item.get("body") or ""))
                for item in items
                if isinstance(item.get("user"), dict)
                and item["user"].get("login") == login
            ]
            if len(items) < 100:
                break
        return found

    async def post_comment(
        self,
        installation_id: int,
        repository: str,
        number: int,
        body: str,
        placement: Placement | None,
    ) -> int:
        token = await self._token(installation_id, repository)
        payload: dict[str, Any]
        if placement is None:
            path, payload = (
                f"repos/{repository}/issues/{number}/comments",
                {"body": body},
            )
        else:
            path = f"repos/{repository}/pulls/{number}/comments"
            payload = {
                "body": body,
                "commit_id": placement.commit,
                "path": placement.path,
                "line": placement.line,
                "side": placement.side,
            }
        response = await self._send("POST", path, token, payload)
        if placement is not None and response.status_code == 422:
            raise PlacementError("GitHub could not place the comment on that line")
        try:
            return int(_payload(self._checked(response))["id"])
        except (KeyError, TypeError, ValueError) as error:
            raise PublicationUncertainError(
                "GitHub did not confirm the comment"
            ) from error

    async def edit_comment(
        self,
        installation_id: int,
        repository: str,
        kind: CommentKind,
        comment_id: int,
        body: str,
    ) -> None:
        token = await self._token(installation_id, repository)
        area = "issues" if kind == "issue" else "pulls"
        self._checked(
            await self._send(
                "PATCH",
                f"repos/{repository}/{area}/comments/{comment_id}",
                token,
                {"body": body},
            )
        )

    async def report_check(
        self,
        installation_id: int,
        repository: str,
        head_sha: str,
        conclusion: str,
        title: str,
        summary: str,
    ) -> None:
        token = await self._token(installation_id, repository)
        found = _payload(
            self._checked(
                await self._send(
                    "GET",
                    f"repos/{repository}/commits/{head_sha}/check-runs",
                    token,
                    params={"check_name": CHECK_NAME, "app_id": self._app_id},
                )
            )
        ).get("check_runs")
        body = {
            "name": CHECK_NAME,
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": conclusion,
            "output": {"title": title, "summary": summary[:CHECK_TEXT_LIMIT]},
        }
        if isinstance(found, list) and found and isinstance(found[0], dict):
            method, path = "PATCH", f"repos/{repository}/check-runs/{found[0]['id']}"
        else:
            method, path = "POST", f"repos/{repository}/check-runs"
        self._checked(await self._send(method, path, token, body))

    async def close(self) -> None:
        await self._client.aclose()

    async def _app_login(self) -> str:
        if self._login is None:
            response = self._checked(await self._send("GET", "app", self._app_token()))
            slug = _payload(response).get("slug")
            if not isinstance(slug, str) or not slug:
                raise CodeHostError("GitHub did not return the app's name")
            self._login = f"{slug}[bot]"
        return self._login

    async def _create(self, mirror: Path, environment: dict[str, str]) -> None:
        try:
            mirror.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as error:
            raise CodeHostError("Could not create the local PR mirror") from error
        code, _ = await run_git(
            self._executable,
            str(mirror.parent),
            (*SAFE_OPTIONS, "init", "--bare", "--quiet", str(mirror)),
            environment,
            FETCH_TIMEOUT_SECONDS,
        )
        if code != 0:
            raise CodeHostError("Could not create the local PR mirror")

    async def _mirror(
        self, mirror: Path, environment: dict[str, str], *arguments: str
    ) -> tuple[int, bytes]:
        return await run_git(
            self._executable,
            str(mirror),
            (*SAFE_OPTIONS, f"--git-dir={mirror}", *arguments),
            environment,
            FETCH_TIMEOUT_SECONDS,
        )

    async def _token(self, installation_id: int, repository: str) -> str:
        key = (installation_id, repository)
        cached = self._tokens.get(key)
        if cached is not None and cached[1] - TOKEN_MARGIN_SECONDS > self._clock():
            return cached[0]
        data = await self._json(
            "POST",
            f"app/installations/{installation_id}/access_tokens",
            self._app_token(),
            {"repositories": [repository.split("/", 1)[1]]},
            missing="The GitHub App is not installed for this repository",
        )
        try:
            token = str(data["token"])
            expires = datetime.fromisoformat(str(data["expires_at"])).timestamp()
        except (KeyError, ValueError) as error:
            raise CodeHostError("GitHub returned an unexpected token format") from error
        self._tokens[key] = (token, expires)
        return token

    def _app_token(self) -> str:
        now = int(self._clock())
        try:
            return jwt.encode(
                {"iat": now - 60, "exp": now + 540, "iss": self._app_id},
                self._private_key,
                algorithm="RS256",
            )
        except (ValueError, TypeError, jwt.PyJWTError) as error:
            raise CodeHostError(
                "The GitHub App private key is unreadable or invalid"
            ) from error

    async def _json(
        self,
        method: str,
        path: str,
        token: str,
        body: dict[str, Any] | None = None,
        *,
        missing: str,
    ) -> dict[str, Any]:
        response = await self._send(method, path, token, body)
        if response.status_code == 404:
            raise CodeHostError(missing)
        return _payload(self._checked(response))

    async def _send(
        self,
        method: str,
        path: str,
        token: str,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                path,
                json=body,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as error:
            raise PublicationUncertainError(
                "GitHub did not respond; try again later"
            ) from error
        if response.status_code in {401, 403}:
            # A revoked installation token must not be reused until it expires.
            self._tokens = {
                key: cached
                for key, cached in self._tokens.items()
                if cached[0] != token
            }
        return response

    @staticmethod
    def _checked(response: httpx.Response) -> httpx.Response:
        status = response.status_code
        if status == 429 or (
            status == 403 and response.headers.get("x-ratelimit-remaining") == "0"
        ):
            raise CodeHostError("GitHub's rate limit was reached; try again later")
        if status in {401, 403}:
            raise CodeHostError(
                "GitHub refused access; check the app installation and permissions"
            )
        if status >= 500:
            raise PublicationUncertainError(f"GitHub returned HTTP {status}")
        if not 200 <= status < 300:
            raise CodeHostError(f"GitHub returned HTTP {status}")
        return response


def _payload(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as error:
        raise CodeHostError("GitHub returned a response that is not JSON") from error
    if not isinstance(data, dict):
        raise CodeHostError("GitHub returned an unexpected response")
    return data


def _items(response: httpx.Response) -> list[dict[str, Any]]:
    try:
        data = response.json()
    except ValueError as error:
        raise CodeHostError("GitHub returned a response that is not JSON") from error
    if not isinstance(data, list):
        raise CodeHostError("GitHub returned an unexpected comment list")
    return [item for item in data if isinstance(item, dict) and "id" in item]
