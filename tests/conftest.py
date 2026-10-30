from pathlib import Path

import pytest

from app.core.settings import Settings
from app.db.migrate import migrate
from app.schemas.review import (
    DiffAnchor,
    EvidenceRef,
    Finding,
    ReviewInputs,
    ReviewResult,
    RuleRef,
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RUSH_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("RUSH_ENVIRONMENT", "test")
    monkeypatch.delenv("META_AI_KEY", raising=False)
    for name in (
        "CLICK_UP_API_TOKEN",
        "RUSH_MCP_CREDENTIALS_DIR",
        "RUSH_CLICKUP_WORKSPACE_ID",
        "RUSH_APPROVED_TICKETS",
        "RUSH_APPROVED_GUIDELINES",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(state_dir=tmp_path / "state", environment="test")


@pytest.fixture
def initialized(settings: Settings) -> Settings:
    migrate(settings.database_path)
    return settings


@pytest.fixture
def review_inputs() -> ReviewInputs:
    return ReviewInputs.model_validate_json(
        (Path(__file__).parent / "fixtures/review-inputs.json").read_bytes()
    )


@pytest.fixture
def review_result(review_inputs: ReviewInputs) -> ReviewResult:
    source = review_inputs.sources[0]
    evidence = EvidenceRef(
        source_id=source.id,
        revision=source.revision,
        content_sha256=source.content_sha256,
        start=5,
        end=5,
    )
    return ReviewResult(
        findings=(
            Finding(
                id="tenant-finding",
                fingerprint="tenant-call-without-tenant",
                run_id="demo-run",
                skill=review_inputs.skills[0],
                rule_ref=RuleRef(id="lantern.tenant-lookup", version="1"),
                category="security",
                severity="high",
                anchor=DiffAnchor(
                    path="customers.py", side="RIGHT", line=5, hunk_id="lookup"
                ),
                problem="The changed lookup omits the caller tenant.",
                consequence="The lookup can return another tenant's customer.",
                trigger_scenario=(
                    "demo-blue requests shared-customer and receives demo-amber."
                ),
                causal_path=(evidence,),
                evidence=(evidence,),
                remediation="Pass the caller tenant ID to the store.",
                verification="code_inspected",
            ),
        )
    )
