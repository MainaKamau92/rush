import io
import json
import sys
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

import app.cli
import app.dependencies
from app.cli import main
from app.core.errors import ModelError
from app.models.model_access import ModelAccess
from app.models.source_access import SourceEvidence, SourceTool


def invoke(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["rush", *args])
    return main()


def test_fresh_install_and_backup_flow(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert invoke(monkeypatch, "health") == 1
    assert "State operation failed" in capsys.readouterr().err
    assert invoke(monkeypatch, "migrate") == 0
    assert json.loads(capsys.readouterr().out) == {"name": "rush", "schema_version": 3}
    assert invoke(monkeypatch, "health") == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == 3
    assert invoke(monkeypatch, "backup", str(tmp_path / "backup.sqlite3")) == 0
    assert json.loads(capsys.readouterr().out)["backup"] == "complete"


def test_cli_configuration_failure_does_not_echo_private_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RUSH_STATE_DIR", "private-customer-value")
    assert invoke(monkeypatch, "health") == 2
    result = capsys.readouterr()
    assert "RUSH_STATE_DIR" in result.err
    assert "private-customer-value" not in result.err


def test_model_check_missing_key_fails_without_a_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("META_AI_KEY", raising=False)
    assert invoke(monkeypatch, "model-check", "--model", "muse-spark-1.3") == 1
    assert "META_AI_KEY" in capsys.readouterr().err


@pytest.mark.parametrize("fail", [False, True])
def test_model_cli_reports_safe_results_and_always_closes_the_service(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fail: bool
) -> None:
    class ControlledAccess:
        closed = False

        async def check(self, model_id: str) -> ModelAccess:
            if fail:
                raise ModelError("Selected Meta model is unavailable")
            return ModelAccess("meta", model_id, model_id, None, {})

        async def close(self) -> None:
            self.closed = True

    access = ControlledAccess()
    monkeypatch.setattr(app.cli, "build_model_access", lambda settings: access)
    assert invoke(monkeypatch, "model-check", "--model", "muse-spark-1.3") == int(fail)
    result = capsys.readouterr()
    if fail:
        assert "unavailable" in result.err and result.out == ""
    else:
        payload = json.loads(result.out)
        assert payload["requested_model"] == payload["resolved_model"]
        assert payload["status"] == "available"
        assert "text" not in payload
    assert access.closed


def test_assembled_model_check_uses_environment_and_closes_http_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("META_AI_KEY", "fixture-token")
    clients = []
    create_client = httpx.AsyncClient

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer fixture-token"
        assert request.url.host == "api.meta.ai"
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "muse-spark-1.3",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "RUSH_OK",
                            }
                        ],
                    }
                ],
            },
        )

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        client = create_client(**kwargs, transport=httpx.MockTransport(handle))
        clients.append(client)
        return client

    monkeypatch.setattr(app.dependencies.httpx, "AsyncClient", client_factory)
    assert invoke(monkeypatch, "model-check", "--model", "muse-spark-1.3") == 0
    output = capsys.readouterr().out
    assert "fixture-token" not in output and "RUSH_OK" not in output
    assert json.loads(output)["status"] == "available"
    assert clients[0].is_closed


def test_source_commands_need_configuration_before_any_connection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert invoke(monkeypatch, "source-status") == 1
    assert "RUSH_MCP_CREDENTIALS_DIR" in capsys.readouterr().err
    monkeypatch.setenv("RUSH_MCP_CREDENTIALS_DIR", str(tmp_path / "credentials"))
    assert invoke(monkeypatch, "source-status") == 0
    status = json.loads(capsys.readouterr().out)
    assert (
        status["credential_available"] is False and status["refresh_available"] is False
    )
    assert invoke(monkeypatch, "source-tools") == 1
    assert "RUSH_CLICKUP_WORKSPACE_ID" in capsys.readouterr().err
    monkeypatch.setenv("RUSH_CLICKUP_WORKSPACE_ID", "9001")
    assert (
        invoke(monkeypatch, "source-read", "--kind", "ticket", "--reference", "86abc1")
        == 1
    )
    assert "run rush source-connect" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["source-tools", "source-read"])
def test_source_cli_prints_only_safe_results_and_closes_the_service(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    class ControlledSourceAccess:
        closed = False

        async def tools(self) -> list[SourceTool]:
            return [
                SourceTool("clickup_get_task", ("task_id",), ("task_id",), True, None)
            ]

        async def read(self, kind: str, reference: str) -> SourceEvidence:
            assert (kind, reference) == ("guideline", "doc/page")
            return SourceEvidence(
                "clickup", "guideline", "clickup_get_document_pages", "r", "c", 12, "t"
            )

        async def close(self) -> None:
            self.closed = True

    access = ControlledSourceAccess()
    monkeypatch.setattr(app.cli, "build_source_access", lambda settings: access)
    arguments = ["--kind", "guideline", "--reference", "doc/page"]
    assert (
        invoke(monkeypatch, command, *(arguments if command == "source-read" else []))
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    if command == "source-read":
        assert payload["status"] == "read" and payload["characters"] == 12
    else:
        assert payload["tools"][0]["name"] == "clickup_get_task"
    assert access.closed


def test_source_connect_prompts_on_stderr_and_reports_credential_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("RUSH_MCP_CREDENTIALS_DIR", str(tmp_path / "credentials"))
    pasted: list[str] = []

    class SigningInAccess:
        def __init__(
            self, show: Callable[[str], None], read: Callable[[], str]
        ) -> None:
            self.show, self.read = show, read

        async def tools(self) -> list[SourceTool]:
            self.show("https://mcp.clickup.com/oauth/authorize?scope=read")
            pasted.append(self.read())
            return []

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        app.cli,
        "build_source_access",
        lambda settings, show, read: SigningInAccess(show, read),
    )
    monkeypatch.setattr(
        sys, "stdin", io.StringIO("http://localhost:8765/callback?code=c\n")
    )
    assert invoke(monkeypatch, "source-connect") == 0
    result = capsys.readouterr()
    assert "oauth/authorize?scope=read" in result.err
    assert "Redirected address" in result.err
    assert pasted == ["http://localhost:8765/callback?code=c\n"]
    payload = json.loads(result.out)
    assert payload["status"] == "connected" and payload["tools"] == 0
    assert payload["credential_available"] is False
