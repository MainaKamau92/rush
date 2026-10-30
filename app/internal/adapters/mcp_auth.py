import json
import os
import tempfile
import time
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx2
from mcp.client.auth import AuthorizationCodeResult
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import ValidationError

from app.core.errors import SourceError
from app.models.source_access import CredentialStatus

REDIRECT_URI = "http://localhost:8765/callback"


class AuthorizationRequiredError(Exception):
    pass


class CredentialRejectedError(Exception):
    pass


class StaticBearerAuth(httpx2.Auth):
    def __init__(self, token: str) -> None:
        self._token = token

    def auth_flow(
        self, request: httpx2.Request
    ) -> Generator[httpx2.Request, httpx2.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request
        if response.status_code in (401, 403):
            raise CredentialRejectedError


async def refuse_authorization(*_: object) -> Any:
    raise AuthorizationRequiredError


def narrow_scope(authorization_url: str, scope: str) -> str:
    parts = urlsplit(authorization_url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    query["scope"] = scope
    return urlunsplit(parts._replace(query=urlencode(query)))


def authorization_result(redirected_url: str) -> AuthorizationCodeResult:
    parts = urlsplit(redirected_url.strip())
    expected = urlsplit(REDIRECT_URI)
    if (parts.scheme, parts.netloc, parts.path) != (
        expected.scheme,
        expected.netloc,
        expected.path,
    ):
        raise SourceError(f"Paste the full address that starts with {REDIRECT_URI}")
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    if "error" in query or not query.get("code"):
        raise SourceError("ClickUp sign-in was not approved; no credential was saved")
    return AuthorizationCodeResult(
        code=query["code"], state=query.get("state"), iss=query.get("iss")
    )


class McpCredentialFile:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._clock = clock

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            raise SourceError(
                "Stored source credentials are unreadable; run rush source-connect"
            ) from None
        if not isinstance(data, dict):
            raise SourceError(
                "Stored source credentials are unreadable; run rush source-connect"
            )
        return data

    def _save(self, **changes: Any) -> None:
        data = {**self._load(), **changes}
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def _model[T: (OAuthToken, OAuthClientInformationFull)](
        self, key: str, model: type[T]
    ) -> T | None:
        value = self._load().get(key)
        if value is None:
            return None
        try:
            return model.model_validate(value)
        except ValidationError:
            raise SourceError(
                "Stored source credentials are unreadable; run rush source-connect"
            ) from None

    async def get_tokens(self) -> OAuthToken | None:
        return self._model("tokens", OAuthToken)

    async def set_tokens(self, tokens: OAuthToken) -> None:
        expires_at = None
        if tokens.expires_in is not None:
            expires_at = self._clock() + tokens.expires_in
        self._save(tokens=tokens.model_dump(mode="json"), expires_at=expires_at)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._model("client_info", OAuthClientInformationFull)

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._save(client_info=client_info.model_dump(mode="json", exclude_none=True))

    def status(self) -> CredentialStatus:
        data = self._load()
        tokens = self._model("tokens", OAuthToken)
        expires_at = data.get("expires_at")
        return CredentialStatus(
            method="oauth",
            credential_available=tokens is not None,
            registered="client_info" in data,
            scope=tokens.scope if tokens else None,
            refresh_available=bool(tokens and tokens.refresh_token),
            expires_in_seconds=(
                None if expires_at is None else round(expires_at - self._clock())
            ),
        )
