"""Tests for cost budget enforcement."""

from __future__ import annotations

from typing import Any

import pytest

from a2a_mesh.coordinator import WorkflowCoordinator
from a2a_mesh.exceptions import BudgetExceededError
from a2a_mesh.models import Task, TaskStatus, Workflow


async def _costed_executor(task: Task) -> Any:
    """Executor that sets a fixed cost per task."""
    task.cost = 0.10
    return f"done:{task.input}"


class TestWorkflowBudgetEnforcement:
    """Tests for max_cost enforcement in workflow execution."""

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises(self) -> None:
        """Workflow that exceeds budget should raise BudgetExceededError."""
        coordinator = WorkflowCoordinator(executor=_costed_executor)
        workflow = Workflow(
            name="expensive",
            tasks=[
                Task(name="step1", input="a"),
                Task(name="step2", depends_on=["step1"]),
                Task(name="step3", depends_on=["step2"]),
            ],
        )
        with pytest.raises(BudgetExceededError):
            await coordinator.execute(workflow, max_cost=0.15)

    @pytest.mark.asyncio
    async def test_budget_not_exceeded_completes(self) -> None:
        """Workflow within budget should complete normally."""
        coordinator = WorkflowCoordinator(executor=_costed_executor)
        workflow = Workflow(
            name="affordable",
            tasks=[
                Task(name="step1", input="a"),
                Task(name="step2", depends_on=["step1"]),
            ],
        )
        result = await coordinator.execute(workflow, max_cost=1.00)
        assert result.status == TaskStatus.COMPLETED
        assert len(result.task_results) == 2

    @pytest.mark.asyncio
    async def test_no_budget_ignores_cost(self) -> None:
        """When max_cost is None, no budget enforcement occurs."""
        coordinator = WorkflowCoordinator(executor=_costed_executor)
        workflow = Workflow(
            name="no-budget",
            tasks=[
                Task(name="s1", input="a"),
                Task(name="s2", depends_on=["s1"]),
                Task(name="s3", depends_on=["s2"]),
            ],
        )
        result = await coordinator.execute(workflow, max_cost=None)
        assert result.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_budget_exceeded_error_attributes(self) -> None:
        coordinator = WorkflowCoordinator(executor=_costed_executor)
        workflow = Workflow(
            name="over-budget",
            tasks=[
                Task(name="step1", input="a"),
                Task(name="step2", depends_on=["step1"]),
            ],
        )
        with pytest.raises(BudgetExceededError) as exc_info:
            await coordinator.execute(workflow, max_cost=0.05)
        assert exc_info.value.budget == 0.05
        assert exc_info.value.spent > 0.05

    @pytest.mark.asyncio
    async def test_parallel_tasks_cumulative_cost(self) -> None:
        """Parallel tasks should have their costs summed for budget check."""
        coordinator = WorkflowCoordinator(executor=_costed_executor)
        workflow = Workflow(
            name="parallel-budget",
            tasks=[
                Task(name="a", input="x"),
                Task(name="b", input="y"),
                Task(name="c", input="z"),
            ],
        )
        # 3 parallel tasks at 0.10 each = 0.30 total
        with pytest.raises(BudgetExceededError):
            await coordinator.execute(workflow, max_cost=0.25)


class TestBudgetExceededErrorMessage:
    """Tests for BudgetExceededError formatting."""

    def test_message_format(self) -> None:
        exc = BudgetExceededError(budget=1.0, spent=1.5)
        assert "1.0" in str(exc) or "1.00" in str(exc)
        assert "1.5" in str(exc) or "1.50" in str(exc)
        assert exc.budget == 1.0
        assert exc.spent == 1.5

    def test_is_workflow_error(self) -> None:
        from a2a_mesh.exceptions import WorkflowError

        assert issubclass(BudgetExceededError, WorkflowError)
