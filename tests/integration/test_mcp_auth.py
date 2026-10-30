import stat
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from app.core.errors import SourceError
from app.internal.adapters.mcp_auth import (
    McpCredentialFile,
    authorization_result,
    narrow_scope,
)

ACCESS = "fixture-access"
REFRESH = "fixture-refresh"
OLD_REFRESH = "fixture-old-refresh"


async def test_credentials_round_trip_privately_and_report_expiry(
    tmp_path: Path,
) -> None:
    path = tmp_path / "credentials" / "clickup.json"
    store = McpCredentialFile(path, clock=lambda: 1000.0)
    assert not store.status().credential_available and await store.get_tokens() is None
    await store.set_client_info(
        OAuthClientInformationFull(
            client_id="client-1", redirect_uris=["http://localhost:8765/callback"]
        )
    )
    await store.set_tokens(
        OAuthToken(access_token=ACCESS, expires_in=600, refresh_token=REFRESH)
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert [item.name for item in path.parent.iterdir()] == ["clickup.json"]
    reloaded = McpCredentialFile(path, clock=lambda: 1400.0)
    tokens = await reloaded.get_tokens()
    client = await reloaded.get_client_info()
    assert tokens is not None and tokens.refresh_token == REFRESH
    assert client is not None and client.client_id == "client-1"
    status = reloaded.status()
    assert (
        status.registered and status.credential_available and status.refresh_available
    )
    assert status.expires_in_seconds == 200
    assert ACCESS not in repr(status)


async def test_rotated_tokens_replace_the_previous_ones(tmp_path: Path) -> None:
    store = McpCredentialFile(tmp_path / "clickup.json")
    await store.set_tokens(
        OAuthToken(access_token=OLD_REFRESH, refresh_token=OLD_REFRESH)
    )
    await store.set_tokens(OAuthToken(access_token=ACCESS, refresh_token=REFRESH))
    tokens = await store.get_tokens()
    assert tokens is not None and tokens.access_token == ACCESS
    assert OLD_REFRESH not in (tmp_path / "clickup.json").read_text()
    assert store.status().expires_in_seconds is None


@pytest.mark.parametrize("content", ["not json", "[]", '{"tokens": {"bad": 1}}'])
async def test_unreadable_credentials_require_reconnect(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "clickup.json"
    path.write_text(content)
    with pytest.raises(SourceError, match="source-connect"):
        await McpCredentialFile(path).get_tokens()


def test_authorization_scope_is_narrowed_without_changing_other_values() -> None:
    url = (
        "https://mcp.clickup.com/oauth/authorize?response_type=code&client_id=c"
        "&state=s1&code_challenge=x&code_challenge_method=S256&scope=read+write"
    )
    narrowed = urlsplit(narrow_scope(url, "read"))
    query = parse_qs(narrowed.query)
    assert narrowed.netloc == "mcp.clickup.com"
    assert query["scope"] == ["read"]
    assert query["state"] == ["s1"] and query["code_challenge"] == ["x"]


def test_redirect_parameters_are_passed_through_for_verification() -> None:
    result = authorization_result(
        " http://localhost:8765/callback?code=c1&state=s1&iss=https%3A%2F%2Fmcp.clickup.com\n"
    )
    assert (result.code, result.state, result.iss) == (
        "c1",
        "s1",
        "https://mcp.clickup.com",
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.example/callback?code=c1&state=s1",
        "http://localhost:9999/callback?code=c1&state=s1",
        "http://localhost:8765/callback?error=access_denied&state=s1",
        "http://localhost:8765/callback?state=s1",
    ],
)
def test_unexpected_or_denied_redirects_are_rejected(url: str) -> None:
    with pytest.raises(SourceError):
        authorization_result(url)


async def test_interrupted_write_keeps_the_previous_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = McpCredentialFile(tmp_path / "clickup.json")
    await store.set_tokens(OAuthToken(access_token=ACCESS, refresh_token=REFRESH))

    def interrupted(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    with monkeypatch.context() as patch, pytest.raises(OSError):
        patch.setattr("app.internal.adapters.mcp_auth.json.dump", interrupted)
        await store.set_tokens(OAuthToken(access_token=OLD_REFRESH))
    tokens = await store.get_tokens()
    assert tokens is not None and tokens.refresh_token == REFRESH
    assert [item.name for item in tmp_path.iterdir()] == ["clickup.json"]
