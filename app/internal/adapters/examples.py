import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.errors import ReviewError
from app.schemas.local_review import ContextFile, LocalReviewRequest


class ExampleContextAdapter:
    def __init__(self, root: Path):
        self._root = root.resolve()
        self._cases: dict[str, Any] = {
            case["id"]: case for case in json.loads(self._read("cases.json"))
        }

    def _read(self, name: str) -> str:
        path = (self._root / name).resolve()
        if not path.is_relative_to(self._root):
            raise ReviewError("Example context must stay inside its corpus")
        return path.read_text()

    def request(self, case_id: str, run_id: str) -> LocalReviewRequest:
        case = self._cases.get(case_id)
        if case is None:
            raise ReviewError(f"Example {case_id} is not a known fixture case")
        team = json.loads(self._read(case["team"]))
        context = []
        if case["ticket"]:
            context.append(
                ContextFile(
                    kind="ticket",
                    reference=Path(case["ticket"]).name,
                    text=self._read(case["ticket"]),
                )
            )
        context.extend(
            ContextFile(
                kind="guideline", reference=Path(name).name, text=self._read(name)
            )
            for name in case["wiki"]
        )
        return LocalReviewRequest(
            run_id=run_id,
            repository="lantern-customer-service",
            head="fixture-head",
            target="fixture-base",
            disclosure="public",
            context=tuple(context),
            rules=self._read(case["rules"]) if case["rules"] else None,
            exceptions=self._read(case["exceptions"]) if case["exceptions"] else None,
            approvers=(team["members"]["approver"],),
            review_time=datetime.fromisoformat(case["review_time"]),
        )
