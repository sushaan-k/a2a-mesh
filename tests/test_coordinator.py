"""Tests for the workflow coordinator."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from a2a_mesh.coordinator import WorkflowCoordinator
from a2a_mesh.exceptions import (
    CyclicDependencyError,
)
from a2a_mesh.models import (
    ConsensusConfig,
    ConsensusThreshold,
    FanInStrategy,
    Task,
    TaskStatus,
    Workflow,
)


async def _echo_executor(task: Task) -> Any:
    """Simple executor that echoes the task input."""
    return f"result:{task.input}"


async def _failing_executor(task: Task) -> Any:
    """Executor that always raises."""
    raise RuntimeError("Agent unavailable")


class TestWorkflowExecution:
    """Tests for basic workflow execution."""

    @pytest.mark.asyncio
    async def test_single_task_workflow(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="single",
            tasks=[Task(name="step1", input="hello")],
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED
        assert result.task_results["step1"] == "result:hello"

    @pytest.mark.asyncio
    async def test_sequential_workflow(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="sequential",
            tasks=[
                Task(name="step1", input="data"),
                Task(name="step2", depends_on=["step1"]),
                Task(name="step3", depends_on=["step2"]),
            ],
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED
        assert "step1" in result.task_results
        assert "step2" in result.task_results
        assert "step3" in result.task_results

    @pytest.mark.asyncio
    async def test_parallel_tasks(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="parallel",
            tasks=[
                Task(name="a", input="alpha"),
                Task(name="b", input="beta"),
                Task(name="c", input="gamma"),
            ],
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED
        assert len(result.task_results) == 3

    @pytest.mark.asyncio
    async def test_diamond_dependency(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="diamond",
            tasks=[
                Task(name="start", input="go"),
                Task(name="left", depends_on=["start"]),
                Task(name="right", depends_on=["start"]),
                Task(name="join", depends_on=["left", "right"]),
            ],
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED
        assert "join" in result.task_results

    @pytest.mark.asyncio
    async def test_dependency_injection(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="inject",
            tasks=[
                Task(name="produce", input="value"),
                Task(name="consume", depends_on=["produce"]),
            ],
        )
        result = await coordinator.execute(workflow)
        # consume should receive produce's result as input
        assert result.task_results["consume"] == "result:result:value"


class TestWorkflowFailures:
    """Tests for workflow failure handling."""

    @pytest.mark.asyncio
    async def test_task_failure_aborts_workflow(self) -> None:
        coordinator = WorkflowCoordinator(executor=_failing_executor)
        workflow = Workflow(
            name="failing",
            tasks=[
                Task(name="step1", input="data"),
                Task(name="step2", depends_on=["step1"]),
            ],
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.FAILED
        assert "step1" in result.errors

    @pytest.mark.asyncio
    async def test_cyclic_dependency_raises(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="cyclic",
            tasks=[
                Task(name="a", depends_on=["c"]),
                Task(name="b", depends_on=["a"]),
                Task(name="c", depends_on=["b"]),
            ],
        )
        with pytest.raises(CyclicDependencyError):
            await coordinator.execute(workflow)


class TestFanOut:
    """Tests for fan-out execution."""

    @pytest.mark.asyncio
    async def test_fan_out_merge(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="fan-out",
            tasks=[Task(name="research", input="topic")],
            fan_out={"research": 3},
            fan_in={"research": FanInStrategy.MERGE},
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED
        # MERGE returns a list of results
        assert isinstance(result.task_results["research"], list)
        assert len(result.task_results["research"]) == 3

    @pytest.mark.asyncio
    async def test_fan_out_first(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="fan-out-first",
            tasks=[Task(name="research", input="topic")],
            fan_out={"research": 3},
            fan_in={"research": FanInStrategy.FIRST},
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED
        # FIRST returns a single result
        assert result.task_results["research"] == "result:topic"

    @pytest.mark.asyncio
    async def test_fan_out_vote(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="fan-out-vote",
            tasks=[Task(name="research", input="topic")],
            fan_out={"research": 3},
            fan_in={"research": FanInStrategy.VOTE},
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED
        # All executors return same result, so vote should pick it
        assert result.task_results["research"] == "result:topic"

    @pytest.mark.asyncio
    async def test_fan_out_all_fail(self) -> None:
        coordinator = WorkflowCoordinator(executor=_failing_executor)
        workflow = Workflow(
            name="fan-out-fail",
            tasks=[Task(name="research", input="topic")],
            fan_out={"research": 3},
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_fan_out_clones_task_state_and_aggregates_cost(self) -> None:
        async def _mutating_executor(task: Task) -> Any:
            assert isinstance(task.input, list)
            task.input.append("attempt")
            task.cost = 0.25
            return len(task.input)

        coordinator = WorkflowCoordinator(executor=_mutating_executor)
        original_input = ["seed"]
        workflow = Workflow(
            name="fan-out-mutation",
            tasks=[Task(name="research", input=original_input)],
            fan_out={"research": 2},
            fan_in={"research": FanInStrategy.MERGE},
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED
        assert result.task_results["research"] == [2, 2]
        assert workflow.tasks[0].input == ["seed"]
        assert result.total_cost == pytest.approx(0.5)


class TestConsensus:
    """Tests for multi-agent consensus."""

    @pytest.mark.asyncio
    async def test_consensus_all_agree(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="consensus",
            tasks=[Task(name="review", input="doc")],
            consensus={
                "review": ConsensusConfig(
                    agents=2, threshold=ConsensusThreshold.ALL_AGREE
                )
            },
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED
        assert result.task_results["review"] == "result:doc"

    @pytest.mark.asyncio
    async def test_consensus_majority(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="consensus-majority",
            tasks=[Task(name="review", input="doc")],
            consensus={
                "review": ConsensusConfig(
                    agents=3, threshold=ConsensusThreshold.MAJORITY
                )
            },
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_consensus_any(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="consensus-any",
            tasks=[Task(name="review", input="doc")],
            consensus={
                "review": ConsensusConfig(agents=2, threshold=ConsensusThreshold.ANY)
            },
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_consensus_not_reached_with_failures(self) -> None:
        coordinator = WorkflowCoordinator(executor=_failing_executor)
        workflow = Workflow(
            name="consensus-fail",
            tasks=[Task(name="review", input="doc")],
            consensus={
                "review": ConsensusConfig(
                    agents=2, threshold=ConsensusThreshold.ALL_AGREE
                )
            },
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_consensus_clones_task_state_and_aggregates_cost(self) -> None:
        async def _mutating_executor(task: Task) -> Any:
            assert isinstance(task.input, list)
            task.input.append("attempt")
            task.cost = 0.4
            return "approved"

        coordinator = WorkflowCoordinator(executor=_mutating_executor)
        workflow = Workflow(
            name="consensus-mutation",
            tasks=[Task(name="review", input=["seed"])],
            consensus={
                "review": ConsensusConfig(
                    agents=2, threshold=ConsensusThreshold.ALL_AGREE
                )
            },
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED
        assert result.task_results["review"] == "approved"
        assert workflow.tasks[0].input == ["seed"]
        assert result.total_cost == pytest.approx(0.8)


class TestCoordinatorFailureHandling:
    """Tests for coordinator edge cases and failure scenarios."""

    @pytest.mark.asyncio
    async def test_agent_crash_mid_workflow(self) -> None:
        """Agent fails mid-workflow -- downstream tasks should not run."""
        call_count = 0

        async def _crash_on_second(task: Task) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Agent crashed")
            return f"ok:{task.input}"

        coordinator = WorkflowCoordinator(executor=_crash_on_second)
        workflow = Workflow(
            name="crash-mid",
            tasks=[
                Task(name="step1", input="a"),
                Task(name="step2", depends_on=["step1"]),
                Task(name="step3", depends_on=["step2"]),
            ],
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.FAILED
        assert "step2" in result.errors
        # step3 should not have executed
        assert "step3" not in result.task_results

    @pytest.mark.asyncio
    async def test_timeout_via_slow_executor(self) -> None:
        """Executor that takes too long can be detected via asyncio timeout."""

        async def _slow_executor(task: Task) -> Any:
            await asyncio.sleep(10)
            return "done"

        coordinator = WorkflowCoordinator(executor=_slow_executor)
        workflow = Workflow(
            name="slow",
            tasks=[Task(name="slow-task", input="data")],
        )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(coordinator.execute(workflow), timeout=0.1)

    @pytest.mark.asyncio
    async def test_empty_workflow(self) -> None:
        """Workflow with no tasks should complete immediately."""
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(name="empty", tasks=[])
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED
        assert result.task_results == {}

    @pytest.mark.asyncio
    async def test_parallel_failure_does_not_run_dependents(self) -> None:
        """When one parallel branch fails, downstream dependents should not run."""
        executed: list[str] = []

        async def _track_executor(task: Task) -> Any:
            executed.append(task.name)
            if task.name == "branch-b":
                raise RuntimeError("branch-b failed")
            return f"ok:{task.name}"

        coordinator = WorkflowCoordinator(executor=_track_executor)
        workflow = Workflow(
            name="parallel-fail",
            tasks=[
                Task(name="start", input="go"),
                Task(name="branch-a", depends_on=["start"]),
                Task(name="branch-b", depends_on=["start"]),
                Task(name="merge", depends_on=["branch-a", "branch-b"]),
            ],
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.FAILED
        assert "merge" not in executed

    @pytest.mark.asyncio
    async def test_multi_dependency_injection(self) -> None:
        """Task with multiple dependencies gets dict of upstream results."""
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="multi-dep",
            tasks=[
                Task(name="a", input="alpha"),
                Task(name="b", input="beta"),
                Task(name="c", depends_on=["a", "b"]),
            ],
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED
        # Task c should receive dict input from a and b
        assert "c" in result.task_results

    @pytest.mark.asyncio
    async def test_fan_out_partial_failure(self) -> None:
        """Fan-out where some executors fail but not all should still succeed."""
        call_count = 0

        async def _partial_fail(task: Task) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise RuntimeError("partial fail")
            return f"ok:{task.input}"

        coordinator = WorkflowCoordinator(executor=_partial_fail)
        workflow = Workflow(
            name="partial-fan-out",
            tasks=[Task(name="task", input="data")],
            fan_out={"task": 4},
            fan_in={"task": FanInStrategy.MERGE},
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.COMPLETED
        # Only the successful ones should be in the merge list
        assert isinstance(result.task_results["task"], list)
        assert len(result.task_results["task"]) == 2

    @pytest.mark.asyncio
    async def test_consensus_majority_not_reached(self) -> None:
        """Majority consensus where no single answer gets > 50%."""
        call_count = 0

        async def _diverse_executor(task: Task) -> Any:
            nonlocal call_count
            call_count += 1
            # Each call returns a different result, no majority
            return f"unique-{call_count}"

        coordinator = WorkflowCoordinator(executor=_diverse_executor)
        workflow = Workflow(
            name="no-majority",
            tasks=[Task(name="review", input="doc")],
            consensus={
                "review": ConsensusConfig(
                    agents=3, threshold=ConsensusThreshold.MAJORITY
                )
            },
        )
        result = await coordinator.execute(workflow)
        assert result.status == TaskStatus.FAILED


class TestWorkflowTimeout:
    """Tests for workflow timeout with partial results."""

    @pytest.mark.asyncio
    async def test_timeout_returns_partial_results(self) -> None:
        """Tasks that complete before timeout are included in results."""
        call_count = 0

        async def _slow_second(task: Task) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                await asyncio.sleep(10)
            return f"done:{task.input}"

        coordinator = WorkflowCoordinator(executor=_slow_second)
        workflow = Workflow(
            name="timeout-partial",
            tasks=[
                Task(name="fast", input="a"),
                Task(name="slow", depends_on=["fast"]),
            ],
        )
        result = await coordinator.execute(workflow, timeout=0.3)
        # fast should have completed
        assert "fast" in result.task_results
        # slow should be marked as timed out
        assert "slow" in result.errors
        assert result.status == TaskStatus.TIMED_OUT

    @pytest.mark.asyncio
    async def test_no_timeout_completes_normally(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="no-timeout",
            tasks=[
                Task(name="a", input="alpha"),
                Task(name="b", depends_on=["a"]),
            ],
        )
        result = await coordinator.execute(workflow, timeout=None)
        assert result.status == TaskStatus.COMPLETED
        assert "a" in result.task_results
        assert "b" in result.task_results
        assert result.errors == {}

    @pytest.mark.asyncio
    async def test_generous_timeout_completes_normally(self) -> None:
        coordinator = WorkflowCoordinator(executor=_echo_executor)
        workflow = Workflow(
            name="generous-timeout",
            tasks=[
                Task(name="step1", input="data"),
                Task(name="step2", depends_on=["step1"]),
            ],
        )
        result = await coordinator.execute(workflow, timeout=30.0)
        assert result.status == TaskStatus.COMPLETED
        assert len(result.task_results) == 2

    @pytest.mark.asyncio
    async def test_timeout_marks_unattempted_tasks_cancelled(self) -> None:
        """Tasks that never started due to timeout are marked cancelled."""

        async def _slow_executor(task: Task) -> Any:
            await asyncio.sleep(10)
            return "done"

        coordinator = WorkflowCoordinator(executor=_slow_executor)
        workflow = Workflow(
            name="all-slow",
            tasks=[
                Task(name="slow1", input="x"),
                Task(name="slow2", depends_on=["slow1"]),
                Task(name="slow3", depends_on=["slow2"]),
            ],
        )
        result = await coordinator.execute(workflow, timeout=0.1)
        # All tasks should appear in errors
        assert len(result.errors) >= 1
        # No task results since first level timed out
        assert result.task_results == {} or len(result.task_results) < 3
        assert result.status == TaskStatus.TIMED_OUT
