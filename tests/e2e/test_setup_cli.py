import json
import sys
from pathlib import Path

import httpx
import pytest

import app.cli
import app.dependencies
from app.cli import main
from app.core.errors import ModelError
from app.models.model_access import ModelAccess


def invoke(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["rush", *args])
    return main()


def test_fresh_install_and_backup_flow(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert invoke(monkeypatch, "health") == 1
    assert "State operation failed" in capsys.readouterr().err
    assert invoke(monkeypatch, "migrate") == 0
    assert json.loads(capsys.readouterr().out) == {"name": "rush", "schema_version": 1}
    assert invoke(monkeypatch, "health") == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == 1
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
