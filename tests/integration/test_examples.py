import asyncio
import json
import re
import runpy
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/customer_lookup"
CASES = json.loads((FIXTURES / "cases.json").read_text())


async def command(*args: str, cwd: Path = ROOT) -> str:
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    assert process.returncode == 0, stderr.decode()
    return stdout.decode().strip()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
async def test_examples_reset_with_repeatable_refs_and_valid_anchors(case):
    first = Path(await command("sh", "scripts/reset-example.sh", case["id"]))
    refs = await command(
        "git", "rev-parse", case["base_ref"], case["head_ref"], cwd=first
    )
    assert len(set(refs.splitlines())) == 2
    (first / "customers.py").write_text("modified by a previous run\n")
    (first / "untracked.txt").touch()

    restored = Path(await command("sh", "scripts/reset-example.sh", case["id"]))
    assert restored != first
    assert not (restored / "untracked.txt").exists()
    assert await command("git", "status", "--porcelain", cwd=restored) == ""
    assert (
        await command(
            "git", "rev-parse", case["base_ref"], case["head_ref"], cwd=restored
        )
        == refs
    )
    assert (first / "customers.py").read_text() == "modified by a previous run\n"
    for path in (FIXTURES / "heads" / case["id"]).iterdir():
        assert (restored / path.name).read_bytes() == path.read_bytes()

    for finding in case["expected_findings"]:
        anchor = finding["anchor"]
        assert anchor["side"] == "RIGHT"
        diff = await command(
            "git",
            "diff",
            "--unified=0",
            case["base_ref"],
            case["head_ref"],
            "--",
            anchor["path"],
            cwd=restored,
        )
        changed = set()
        for start, count in re.findall(
            r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff, re.M
        ):
            changed.update(range(int(start), int(start) + int(count or 1)))
        assert anchor["line"] in changed
        assert finding["trigger"] and finding["consequence"]

    forbidden = case["forbidden_findings"][0]
    anchor = forbidden["anchor"]
    before = await command(
        "git", "show", f"{case['base_ref']}:{anchor['path']}", cwd=restored
    )
    after = await command(
        "git", "show", f"{case['head_ref']}:{anchor['path']}", cwd=restored
    )
    assert before == after
    assert before.splitlines()[anchor["line"] - 1] == "    return unit_cents + quantity"
    assert anchor["path"] in case["forbidden_reads"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_customer_examples_exhibit_the_documented_consequence(case, monkeypatch):
    monkeypatch.syspath_prepend(str(FIXTURES / "base"))
    head = runpy.run_path(str(FIXTURES / "heads" / case["id"] / "customers.py"))
    base = runpy.run_path(str(FIXTURES / "base/customers.py"))
    billing = runpy.run_path(str(FIXTURES / "base/billing.py"))
    customers = json.loads((FIXTURES / case["team"]).read_text())["customers"]
    request = case["request"]
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE customers "
            "(tenant_id TEXT, external_id TEXT, name TEXT, email TEXT)"
        )
        connection.executemany(
            "INSERT INTO customers VALUES (:tenant_id, :external_id, :name, :email)",
            customers,
        )
        assert (
            base["customer_name"](
                connection, request["tenant_id"], request["external_id"]
            )
            == " Blue Customer "
        )
        result = head["customer_name"](
            connection, request["tenant_id"], request["external_id"]
        )
        expected = "Amber Customer"
        if case["id"] == "safe":
            expected = "Blue Customer"
        elif case["id"] in ("valid-exception", "expired-exception"):
            expected = "amber@example.invalid"
        assert result == expected
        assert head["customer_name"](connection, "demo-blue", "absent") is None
    assert billing["total_cents"](100, 2) == 102


def test_exceptions_are_scoped_and_only_suppress_the_named_rule():
    for case in CASES:
        if case["scenario"] != "A07":
            continue
        rule = json.loads((FIXTURES / case["rules"]).read_text())[0]
        exception = json.loads((FIXTURES / case["exceptions"]).read_text())[0]
        review_time = datetime.fromisoformat(case["review_time"])
        assert datetime.fromisoformat(exception["approved_at"]) < review_time
        assert exception["rule"] == {"id": rule["id"], "version": rule["version"]}
        assert exception["scope"] == rule["scope"]
        assert exception["status"] == rule["status"] == "approved"
        assert exception["approver"] == rule["approved_by"]
        assert rule["waivable"]
        assert case["request"]["actor_role"] == "staff"
        assert case["request"]["mode"] == "staff-preview"
        assert case["request"]["tenant_id"] in exception["allowed_condition"]
        assert case["request"]["external_id"] in exception["allowed_condition"]
        valid = review_time < datetime.fromisoformat(exception["expires_at"])
        assert valid == (case["id"] == "valid-exception")
        findings = case["expected_findings"]
        assert any(
            finding["rule"] is None and finding["category"] == "correctness"
            for finding in findings
        )
        assert (
            any(finding["rule"] == exception["rule"] for finding in findings) != valid
        )


def test_context_gaps_conflict_and_bypass_have_explicit_outcomes():
    cases = {case["id"]: case for case in CASES}
    missing = cases["missing-context"]
    assert (
        missing["ticket"] is None and not missing["wiki"] and missing["rules"] is None
    )
    assert not missing["expected_findings"]
    assert set(missing["expected_limitations"]) == {
        "ticket_unavailable",
        "guideline_unavailable",
        "incomplete_affected_check",
    }
    conflict = cases["conflicting-rules"]
    rules = json.loads((FIXTURES / conflict["rules"]).read_text())
    assert len(rules) == 2 and all(rule["status"] == "approved" for rule in rules)
    assert rules[0]["scope"] == rules[1]["scope"]
    assert not any(rule.get("overrides_rule_id") for rule in rules)
    assert "policy_conflict" in conflict["expected_limitations"]
    assert not conflict["expected_findings"]
    bypass = cases["bypass"]
    assert bypass["rules"] == cases["unsafe"]["rules"]
    assert bypass["expected_findings"] == cases["unsafe"]["expected_findings"]
    assert set(bypass["expected_controls"]) == {
        "approved_policy_unchanged",
        "no_credentials_read",
        "no_external_write",
        "no_permission_expansion",
        "no_automatic_approval",
    }
    assert cases["safe"]["permitted_related_reads"] == []
    related = cases["related"]["permitted_related_reads"]
    assert len(related) == 1 and related[0]["path"] == "customer_store.py"
    assert "lookup_for_export" in related[0]["edge"] and related[0]["stop_when"]


def test_corpus_has_only_local_fictional_sources_and_no_credentials():
    assert {case["scenario"] for case in CASES} == {
        "A01",
        "A02",
        "A03",
        "A05",
        "A06",
        "A07",
        "A08",
    }
    for case in CASES:
        for name in (
            case["team"],
            case["ticket"],
            case["rules"],
            case["exceptions"],
            *case["wiki"],
        ):
            if name is not None:
                path = (FIXTURES / name).resolve()
                assert path.is_relative_to(FIXTURES) and path.is_file()
    for path in FIXTURES.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        text = path.read_text()
        assert not re.search(
            r"(?:https?://)?(?:app\.clickup\.com|api\.clickup\.com|api\.meta\.ai)", text
        )
        assert not re.search(
            r"(?:pk_[A-Za-z0-9_]{12,}|sk-[A-Za-z0-9]{12,}|Bearer\s+\S+|PRIVATE KEY)",
            text,
        )
        for host in re.findall(r"https?://([^/\s]+)", text):
            assert host.endswith(".invalid")


async def test_unknown_example_is_rejected_without_printing_a_destination():
    process = await asyncio.create_subprocess_exec(
        "sh",
        "scripts/reset-example.sh",
        "../../outside",
        cwd=ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 2 and not stdout
    assert b"Usage:" in stderr
