import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app import dependencies
from app.core.errors import ReviewError
from app.db.repositories.reviews import SQLiteReviewRepository
from app.schemas.model_review import ReviewPermissions, ReviewTask
from app.schemas.review import ModelConfiguration, ReviewSettings
from tests.integration.test_code_change_reader import run


@pytest.mark.parametrize("mode", ["candidate", "invalid", "denied"])
async def test_real_git_meta_mapping_and_sqlite_keep_review_stage_outcomes(
    mode, initialized, review_inputs, monkeypatch
):
    example = Path(await run("sh", "scripts/reset-example.sh", "related"))
    broker = dependencies.build_investigation(example)
    scope = (await broker.start("fixture-head", target="fixture-base")).scope
    inputs = review_inputs.model_copy(
        update={
            "head_sha": scope.head_sha,
            "target_sha": scope.target_sha,
            "merge_base_sha": scope.base_sha,
            "scope_manifest_sha256": scope.manifest_sha256(),
            "sources": (),
            "settings": ReviewSettings(
                models=(
                    ModelConfiguration(
                        task="review",
                        model_id="muse-spark-1.3",
                        adapter_version="0.2.0",
                        max_output_tokens=2048,
                    ),
                )
            ),
        }
    )
    permissions = ("repo.read_snippet", "repo.find_symbol")
    task = ReviewTask(
        skill=inputs.skills[0],
        instructions="Inspect the fictional customer lookup.",
        code_disclosure="public",
        permissions=ReviewPermissions(
            runtime=permissions,
            repository=permissions,
            skill=() if mode == "denied" else permissions,
        ),
    )
    requests = []
    real_client = httpx.AsyncClient

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        data = json.loads(body["input"])
        if mode == "invalid":
            text = "fixture-sensitive-invalid-output"
        elif len(requests) == 1:
            hunk = data["change"]["files"][0]["hunks"][0]["id"]
            text = json.dumps(
                {
                    "kind": "request_context",
                    "requests": [
                        {
                            "question_id": "tenant",
                            "question": "Does the lookup keep the tenant boundary?",
                            "origin_hunk_id": hunk,
                            "relationship": "callee",
                            "target": "customer_store.py",
                            "expected_evidence": "Query tenant scoping",
                            "start_line": 1,
                            "end_line": 14,
                        }
                    ],
                }
            )
        elif mode == "denied":
            text = '{"kind":"done"}'
        else:
            hunk = data["change"]["files"][0]["hunks"][0]["id"]
            source = data["evidence_catalog"][0]
            read = next(item for item in data["reads"] if item["action"] == "read")
            evidence = {
                "source_id": source["source_id"],
                "start": 1,
                "end": 1,
            }
            text = json.dumps(
                {
                    "kind": "candidates",
                    "findings": [
                        {
                            "category": "security",
                            "severity": "high",
                            "anchor": {
                                "path": "customers.py",
                                "side": "RIGHT",
                                "line": 5,
                                "hunk_id": hunk,
                            },
                            "problem": "The export query has no tenant condition.",
                            "consequence": "Another tenant's customer can be returned.",
                            "trigger_scenario": "Two tenants use the same external ID.",
                            "evidence": [evidence],
                            "causal_path": [evidence],
                            "remediation": "Keep the tenant condition.",
                        }
                    ],
                    "answers": [
                        {
                            "question_id": "tenant",
                            "answer": "The helper's scope is known.",
                            "evidence_ids": [read["read_id"]],
                        }
                    ],
                }
            )
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
                "usage": {"input_tokens": 25, "output_tokens": 10, "total_tokens": 35},
            },
        )

    monkeypatch.setattr(
        dependencies.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    settings = initialized.model_copy(
        update={"meta_api_key": SecretStr("fixture-meta-key")}
    )
    service = dependencies.build_model_review(settings, broker)
    try:
        report = await service.run("assembled-model-run", inputs, task)
    finally:
        await service.close()
    stored = await SQLiteReviewRepository(settings.database_path).get(
        "assembled-model-run"
    )
    assert stored.progress.result == report.result and stored.inputs == inputs
    assert len(requests) == 2 and report.result.usage.model_calls == 2
    assert stored.progress.result.usage.input_tokens == 50
    assert all(
        request["store"] is False and "tools" not in request for request in requests
    )
    assert "fixture-meta-key" not in report.model_dump_json()
    assert "fixture-sensitive-invalid-output" not in report.model_dump_json()
    if mode == "candidate":
        assert report.status == "ready" and stored.status == "validating"
        assert len(stored.progress.result.candidate_findings) == 1
        assert (
            len(stored.progress.result.context_sources) == len(scope.files[0].hunks) + 1
        )
        with pytest.raises(ReviewError, match="Unvalidated"):
            await dependencies.build_review_records(settings).advance(
                "assembled-model-run", "publishing", "Premature publication"
            )
    else:
        assert stored.status == ("failed" if mode == "invalid" else "partial")
        assert stored.progress.result.findings == ()


async def test_pre_model_stage_record_data_remains_readable(
    initialized, review_inputs, review_result
):
    import sqlite3

    records = dependencies.build_review_records(initialized)
    created = await records.create("demo-run", review_inputs)
    old_progress = {
        "events": created.progress.model_dump(mode="json")["events"],
        "result": {
            "findings": [
                item.model_dump(mode="json") for item in review_result.findings
            ],
            "limitations": [],
            "usage": review_result.usage.model_dump(mode="json"),
        },
    }
    with sqlite3.connect(initialized.database_path) as connection:
        connection.execute(
            "UPDATE review_runs SET progress_json = ? WHERE run_id = ?",
            (json.dumps(old_progress), "demo-run"),
        )
    loaded = await records.get("demo-run")
    assert loaded.progress.result.findings == review_result.findings
    assert loaded.progress.result.candidate_findings == ()
    assert loaded.progress.result.model_attempts == ()
    assert loaded.progress.result.model_capabilities is None
    await records.advance("demo-run", "preparing", "Legacy data still supports updates")
