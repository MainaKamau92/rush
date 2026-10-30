import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar, get_args

from app.core.errors import InvestigationError
from app.schemas.investigation import BudgetCounter, BudgetResource
from app.schemas.review import Limitation, ReviewLimits

Result = TypeVar("Result")
REQUIRED_BUDGETS = {"changed_files", "changed_lines", "model_calls", "wall_seconds"}


class BudgetExceededError(InvestigationError):
    pass


class ReviewBudget:
    def __init__(self, limits: ReviewLimits, clock: Callable[[], float]) -> None:
        self.limits = limits
        self._clock = clock
        self._started_at = clock()
        self._used: dict[BudgetResource, int] = dict.fromkeys(
            get_args(BudgetResource), 0
        )
        self._limitations: dict[str, Limitation] = {}
        self.active_operations = 0

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self._started_at)

    @property
    def limitations(self) -> tuple[Limitation, ...]:
        return tuple(self._limitations.values())

    def remaining(self, resource: BudgetResource) -> int:
        return int(getattr(self.limits, resource)) - self._used[resource]

    def _exceeded(self, resource: str) -> BudgetExceededError:
        reason = f"Review budget exhausted: {resource}"
        self._limitations[resource] = Limitation(
            code="budget",
            reason=reason,
            affects_completeness=resource in REQUIRED_BUDGETS,
        )
        return BudgetExceededError(reason)

    def seconds_left(self) -> float:
        remaining = self.limits.wall_seconds - self.elapsed_seconds
        if remaining <= 0 or "wall_seconds" in self._limitations:
            raise self._exceeded("wall_seconds")
        return remaining

    def charge(self, resource: BudgetResource, amount: int = 1) -> None:
        self.seconds_left()
        if amount < 0:
            raise InvestigationError("Budget charges cannot be negative")
        if amount > self.remaining(resource):
            raise self._exceeded(resource)
        self._used[resource] += amount

    def depth(self, value: int) -> None:
        self.seconds_left()
        if value > self.limits.relationship_depth:
            raise self._exceeded("relationship_depth")
        self._used["relationship_depth"] = max(self._used["relationship_depth"], value)

    def snapshot(self) -> tuple[BudgetCounter, ...]:
        return tuple(
            BudgetCounter(
                resource=name, used=value, limit=int(getattr(self.limits, name))
            )
            for name, value in self._used.items()
        )

    async def perform(self, operation: Callable[[], Awaitable[Result]]) -> Result:
        timeout = asyncio.timeout(self.seconds_left())
        self.active_operations += 1
        try:
            async with timeout:
                result = await operation()
        except TimeoutError as error:
            if not timeout.expired():
                raise
            raise self._exceeded("wall_seconds") from error
        finally:
            self.active_operations -= 1
        self.seconds_left()
        return result
