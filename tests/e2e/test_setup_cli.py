import asyncio
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


async def reset_example(case: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "sh",
        "scripts/reset-example.sh",
        case,
        cwd=Path(__file__).resolve().parents[2],
        stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()
    assert process.returncode == 0
    return stdout.decode().strip()


def test_change_read_loads_an_example_without_a_server_or_settings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    example = asyncio.run(reset_example("unsafe"))
    monkeypatch.setenv("RUSH_STATE_DIR", "relative-and-invalid")
    arguments = ("change-read", "--repository", example, "--head", "fixture-head")

    assert invoke(monkeypatch, *arguments, "--target", "fixture-base") == 0
    output = json.loads(capsys.readouterr().out)
    assert (output["status"], output["comparison"]) == ("complete", "merge_base")
    assert [change["new_path"] for change in output["files"]] == ["customers.py"]
    assert len(output["scope_sha256"]) == 64

    assert invoke(monkeypatch, *arguments, "--base", "missing-version") == 1
    assert "not available" in capsys.readouterr().err
    monkeypatch.setattr(app.dependencies.shutil, "which", lambda _: None)
    assert invoke(monkeypatch, *arguments, "--base", "fixture-base") == 1
    assert "Git is not installed" in capsys.readouterr().err


def meta_reply(body: dict[str, object], text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "status": "completed",
            "model": body["model"],
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
            "usage": {"input_tokens": 30, "output_tokens": 10, "total_tokens": 40},
        },
    )


def test_local_review_writes_reports_without_a_server(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    corpus = root / "tests/fixtures/customer_lookup"
    example = asyncio.run(reset_example("unsafe"))
    assert invoke(monkeypatch, "migrate") == 0
    capsys.readouterr()
    real_client = httpx.AsyncClient
    instructions: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        instructions.append(str(body["instructions"]))
        if "critique model" in body["instructions"]:
            return meta_reply(
                body,
                json.dumps(
                    {
                        "kind": "critique",
                        "verdicts": [
                            {"candidate": 0, "verdict": "keep", "reason": "Supported."}
                        ],
                    }
                ),
            )
        if "# Team standards" not in body["instructions"]:
            return meta_reply(body, '{"kind": "done"}')
        hunk = json.loads(body["input"])["change"]["files"][0]["hunks"][0]
        position = next(
            index
            for index, line in enumerate(hunk["lines"], start=1)
            if line["new_line"] == 5
        )
        evidence = [
            {"source_id": f"diff:{hunk['id']}", "start": position, "end": position}
        ]
        return meta_reply(
            body,
            json.dumps(
                {
                    "kind": "candidates",
                    "findings": [
                        {
                            "rule_ref": {"id": "lantern.tenant-lookup", "version": "1"},
                            "category": "security",
                            "severity": "high",
                            "anchor": {
                                "path": "customers.py",
                                "side": "RIGHT",
                                "line": 5,
                                "hunk_id": hunk["id"],
                            },
                            "problem": "The lookup omits the tenant.",
                            "consequence": "Another tenant's name is returned.",
                            "trigger_scenario": "demo-blue gets demo-amber.",
                            "causal_path": evidence,
                            "evidence": evidence,
                            "remediation": "Pass tenant_id.",
                        }
                    ],
                }
            ),
        )

    monkeypatch.setattr(
        app.dependencies.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    monkeypatch.setenv("META_AI_KEY", "fixture-meta-key")
    monkeypatch.chdir(root)
    output = tmp_path / "report"
    arguments = [
        "review",
        "--repository",
        example,
        "--target",
        "fixture-base",
        "--head",
        "fixture-head",
        "--ticket",
        str(corpus / "context/ticket.md"),
        "--guideline",
        str(corpus / "context/guideline.md"),
        "--rules",
        str(corpus / "context/rules.json"),
        "--output",
        str(output),
    ]
    assert invoke(monkeypatch, *arguments, "--disclosure", "public") == 0
    result = json.loads(capsys.readouterr().out)
    assert (result["status"], result["findings"]) == ("completed", 1)
    report = json.loads((output / "review.json").read_text())
    assert report["findings"][0]["rule_ref"]["id"] == "lantern.tenant-lookup"
    assert report["application_tests_executed"] is False
    assert [skill["id"] for skill in report["skills"]] == [
        "rush.correctness",
        "rush.team-standards",
        "rush.ticket-intent",
    ]
    assert (output / "review.md").read_text().startswith("# Review complete")
    assert len(instructions) == 4
    assert "fixture-meta-key" not in (output / "review.json").read_text()

    assert invoke(monkeypatch, *arguments) == 1
    assert "failed" in capsys.readouterr().out
    assert invoke(monkeypatch, *arguments[:-2], "--ticket", "absent.md") == 1
    assert "Cannot read absent.md" in capsys.readouterr().err
    assert invoke(monkeypatch, *arguments, "--skills", str(tmp_path)) == 1
    assert "Approved skill list is missing" in capsys.readouterr().err
    inside = str(Path(example) / "skills")
    assert invoke(monkeypatch, *arguments, "--skills", inside) == 1
    assert "outside the reviewed repository" in capsys.readouterr().err
    empty = tmp_path / "empty.md"
    empty.write_text(" \n")
    assert invoke(monkeypatch, *arguments[:-2], "--ticket", str(empty)) == 1
    assert "is empty" in capsys.readouterr().err


def test_skill_list_shows_verified_starter_skills(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[2])
    monkeypatch.setenv("RUSH_STATE_DIR", "relative-and-invalid")
    assert invoke(monkeypatch, "skill-list") == 0
    skills = json.loads(capsys.readouterr().out)["skills"]
    assert [skill["id"] for skill in skills] == [
        "rush.correctness",
        "rush.team-standards",
        "rush.ticket-intent",
    ]
    assert all(skill["model"] == "muse-spark-1.3" for skill in skills)
