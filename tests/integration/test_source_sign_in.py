import base64
import hashlib
import json
import stat
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2
import pytest
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

import app.dependencies
from app.core.errors import SourceError
from app.core.settings import Settings
from app.dependencies import build_source_access, source_credential_status

ORIGIN = "https://mcp.clickup.com"
ISSUED = "fixture-issued"
AFTER_REVOCATION = "fixture-after-revocation"


class ClickUpDouble(httpx2.AsyncBaseTransport):
    def __init__(self) -> None:
        server = MCPServer("clickup-double")

        @server.tool()
        def clickup_get_task(task_id: str, workspace_id: str | None = None) -> str:
            return f"Fictional ticket {task_id}"

        self.server = server
        self.mcp = httpx2.ASGITransport(
            server.streamable_http_app(
                stateless_http=True,
                transport_security=TransportSecuritySettings(
                    enable_dns_rebinding_protection=False
                ),
            )
        )
        self.accepted_bearer = ISSUED
        self.requests: list[httpx2.Request] = []
        self.registration: dict[str, Any] = {}
        self.challenge = ""

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/.well-known/oauth-protected-resource/mcp":
            return httpx2.Response(
                200,
                json={
                    "resource": f"{ORIGIN}/mcp",
                    "authorization_servers": [ORIGIN],
                    "scopes_supported": ["read", "write"],
                },
            )
        if path == "/.well-known/oauth-authorization-server":
            return httpx2.Response(
                200,
                json={
                    "issuer": ORIGIN,
                    "authorization_endpoint": f"{ORIGIN}/oauth/authorize",
                    "token_endpoint": f"{ORIGIN}/oauth/token",
                    "registration_endpoint": f"{ORIGIN}/oauth/register",
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code"],
                    "token_endpoint_auth_methods_supported": ["none"],
                    "scopes_supported": ["read", "write"],
                    "code_challenge_methods_supported": ["S256"],
                    "authorization_response_iss_parameter_supported": True,
                },
            )
        if path == "/oauth/register":
            self.registration = json.loads(await request.aread())
            return httpx2.Response(
                201, json={**self.registration, "client_id": "client-1"}
            )
        if path == "/oauth/token":
            form = parse_qs((await request.aread()).decode())
            verifier = form["code_verifier"][0].encode()
            digest = base64.urlsafe_b64encode(hashlib.sha256(verifier).digest())
            if (
                form["code"] != ["code-1"]
                or digest.decode().rstrip("=") != self.challenge
            ):
                return httpx2.Response(400, json={"error": "invalid_grant"})
            return httpx2.Response(
                200,
                json={
                    "access_token": self.accepted_bearer,
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "scope": "read",
                },
            )
        if request.headers.get("authorization") == f"Bearer {self.accepted_bearer}":
            return await self.mcp.handle_async_request(request)
        return httpx2.Response(
            401,
            headers={
                "WWW-Authenticate": 'Bearer error="inaccepted_bearer", '
                f'resource_metadata="{ORIGIN}/.well-known/oauth-protected-resource/mcp"'
            },
        )

    def running(self) -> AbstractAsyncContextManager[None]:
        return self.server.session_manager.run()

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


@pytest.fixture
def clickup(monkeypatch: pytest.MonkeyPatch) -> ClickUpDouble:
    double = ClickUpDouble()
    create_client = httpx2.AsyncClient

    def client_factory(**kwargs: Any) -> httpx2.AsyncClient:
        return create_client(**kwargs, transport=double)

    monkeypatch.setattr(app.dependencies.httpx2, "AsyncClient", client_factory)
    return double


@pytest.fixture
def source_settings(tmp_path: Path) -> Settings:
    return Settings(
        state_dir=tmp_path / "state",
        mcp_credentials_dir=tmp_path / "credentials",
        clickup_workspace_id="9001",
        approved_tickets="86abc1",
    )


async def sign_in(settings: Settings, clickup: ClickUpDouble, **reply: str) -> str:
    shown: list[str] = []

    def show(url: str) -> None:
        shown.append(url)
        clickup.challenge = parse_qs(urlsplit(url).query)["code_challenge"][0]

    def read() -> str:
        query = parse_qs(urlsplit(shown[0]).query)
        params = {"code": "code-1", "state": query["state"][0], "iss": ORIGIN}
        return "http://localhost:8765/callback?" + urlencode({**params, **reply})

    service = build_source_access(settings, show, read)
    try:
        await service.tools()
    finally:
        await service.close()
    return shown[0]


async def test_sign_in_requests_read_scope_and_stores_private_credentials(
    clickup: ClickUpDouble, source_settings: Settings
) -> None:
    async with clickup.running():
        shown = await sign_in(source_settings, clickup)
        query = parse_qs(urlsplit(shown).query)
        assert shown.startswith(f"{ORIGIN}/oauth/authorize?")
        assert query["scope"] == ["read"]
        assert query["code_challenge_method"] == ["S256"]
        assert query["redirect_uri"] == ["http://localhost:8765/callback"]
        assert clickup.registration["client_name"] == "rush"
        assert clickup.registration["redirect_uris"] == [
            "http://localhost:8765/callback"
        ]
        assert source_settings.mcp_credentials_dir is not None
        stored = source_settings.mcp_credentials_dir / "clickup.json"
        assert stat.S_IMODE(stored.stat().st_mode) == 0o600
        status = source_credential_status(source_settings)
        assert (
            status.credential_available and status.registered and status.scope == "read"
        )
        assert not status.refresh_available
        assert (
            status.expires_in_seconds is not None
            and 3590 < status.expires_in_seconds <= 3600
        )


async def test_unattended_read_reuses_stored_sign_in_without_oauth(
    clickup: ClickUpDouble, source_settings: Settings
) -> None:
    async with clickup.running():
        await sign_in(source_settings, clickup)
        clickup.requests.clear()
        service = build_source_access(source_settings)
        evidence = await service.read("ticket", "86abc1")
        await service.close()
        assert evidence.tool == "clickup_get_task"
        assert evidence.characters == len("Fictional ticket 86abc1")
        assert not any(
            path.startswith(("/oauth", "/.well-known")) for path in clickup.paths()
        )


async def test_rejected_credential_requires_reconnect_without_prompting(
    clickup: ClickUpDouble, source_settings: Settings
) -> None:
    async with clickup.running():
        await sign_in(source_settings, clickup)
        clickup.accepted_bearer = AFTER_REVOCATION
        clickup.requests.clear()
        service = build_source_access(source_settings)
        with pytest.raises(SourceError, match="authorization is required"):
            await service.read("ticket", "86abc1")
        await service.close()
        assert "/oauth/token" not in clickup.paths()
        assert "/oauth/register" not in clickup.paths()


async def test_unattended_use_without_sign_in_sends_nothing(
    clickup: ClickUpDouble, source_settings: Settings
) -> None:
    with pytest.raises(SourceError, match="run rush source-connect"):
        build_source_access(source_settings)
    assert clickup.requests == []


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        ({"error": "access_denied"}, "not approved"),
        ({"state": "forged-state"}, "sign-in failed"),
    ],
)
async def test_denied_or_forged_sign_in_saves_no_token(
    clickup: ClickUpDouble,
    source_settings: Settings,
    reply: dict[str, str],
    message: str,
) -> None:
    async with clickup.running():
        with pytest.raises(SourceError, match=message):
            await sign_in(source_settings, clickup, **reply)
        assert "/oauth/token" not in clickup.paths()
        assert not source_credential_status(source_settings).credential_available


async def test_configured_token_reads_without_oauth_or_stored_credentials(
    clickup: ClickUpDouble, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLICK_UP_API_TOKEN", ISSUED)
    settings = Settings(
        state_dir=tmp_path / "state",
        clickup_workspace_id="9001",
        approved_tickets="86abc1",
    )
    async with clickup.running():
        service = build_source_access(settings)
        evidence = await service.read("ticket", "86abc1")
        await service.close()
        clickup.accepted_bearer = AFTER_REVOCATION
        service = build_source_access(settings)
        with pytest.raises(SourceError, match="rejected the configured credential"):
            await service.read("ticket", "86abc1")
        await service.close()
    assert evidence.tool == "clickup_get_task"
    assert not any(
        path.startswith(("/oauth", "/.well-known")) for path in clickup.paths()
    )
    status = source_credential_status(settings)
    assert status.method == "api_token" and status.credential_available
    assert ISSUED not in repr(settings) and ISSUED not in repr(status)
