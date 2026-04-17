"""Workflow coordinator for a2a-mesh.

Orchestrates multi-agent workflows expressed as directed acyclic graphs.
Handles dependency resolution, fan-out parallelism, fan-in aggregation,
and multi-agent consensus.
"""

from __future__ import annotations

import asyncio
import copy
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from a2a_mesh._logging import get_logger
from a2a_mesh.exceptions import (
    ConsensusNotReachedError,
    CyclicDependencyError,
    TaskExecutionError,
)
from a2a_mesh.models import (
    ConsensusConfig,
    ConsensusThreshold,
    FanInStrategy,
    Task,
    TaskStatus,
    Workflow,
    WorkflowResult,
)

logger = get_logger(__name__)

# Type alias for the task executor callback
TaskExecutor = Any  # Callable[[Task], Awaitable[Any]] — relaxed for flexibility


class WorkflowCoordinator:
    """Executes workflow DAGs with dependency management.

    The coordinator topologically sorts tasks, runs independent tasks in
    parallel, handles fan-out/fan-in patterns, and enforces consensus
    requirements.

    Attributes:
        executor: Async callable that executes a single task and returns
            its result.
    """

    def __init__(self, executor: TaskExecutor) -> None:
        """Initialize the coordinator.

        Args:
            executor: An async callable ``(Task) -> Any`` that dispatches
                a single task to an agent and returns the result.
        """
        self.executor = executor

    async def execute(self, workflow: Workflow) -> WorkflowResult:
        """Execute a complete workflow.

        Tasks are scheduled according to their dependency graph. Independent
        tasks run concurrently. Fan-out tasks are replicated across multiple
        agents, and fan-in merges their results.

        Args:
            workflow: The workflow to execute.

        Returns:
            A WorkflowResult containing all task outputs and metadata.

        Raises:
            CyclicDependencyError: If the dependency graph has cycles.
            TaskExecutionError: If a task fails and cannot be recovered.
        """
        execution_order = self._topological_sort(workflow)
        logger.info(
            "workflow.started",
            workflow_id=workflow.workflow_id,
            task_count=len(workflow.tasks),
            order=[t.name for t in execution_order],
        )

        result = WorkflowResult(
            workflow_id=workflow.workflow_id,
            started_at=datetime.now(UTC),
        )
        task_results: dict[str, Any] = {}

        # Group tasks into levels (tasks at the same level have no
        # dependencies on each other and can run concurrently)
        levels = self._build_levels(execution_order, workflow)

        for level in levels:
            coros = []
            for task in level:
                # Inject upstream results as input
                task = self._inject_dependencies(task, task_results)
                coros.append(self._execute_task(task, workflow, task_results))

            level_results = await asyncio.gather(*coros, return_exceptions=True)

            for task, res in zip(level, level_results, strict=True):
                if isinstance(res, BaseException):
                    result.status = TaskStatus.FAILED
                    error_msg = str(res)
                    result.errors[task.name] = error_msg
                    logger.error(
                        "workflow.task_failed",
                        task=task.name,
                        error=error_msg,
                    )
                    # Fail-fast: abort remaining levels
                    result.completed_at = datetime.now(UTC)
                    result.task_results = task_results
                    return result

        result.task_results = task_results
        result.total_cost = sum(t.cost for t in workflow.tasks if t.cost > 0)
        result.completed_at = datetime.now(UTC)
        logger.info(
            "workflow.completed",
            workflow_id=workflow.workflow_id,
            total_cost=result.total_cost,
        )
        return result

    async def _execute_task(
        self,
        task: Task,
        workflow: Workflow,
        task_results: dict[str, Any],
    ) -> None:
        """Execute a single task, handling fan-out and consensus."""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(UTC)

        fan_out_count = workflow.fan_out.get(task.name, 1)

        try:
            if fan_out_count > 1:
                results = await self._fan_out(task, fan_out_count)
                fan_in_strategy = workflow.fan_in.get(task.name, FanInStrategy.MERGE)
                merged = self._fan_in(results, fan_in_strategy)
                task.result = merged
            elif task.name in workflow.consensus:
                config = workflow.consensus[task.name]
                task.result = await self._consensus(task, config)
            else:
                task.result = await self.executor(task)

            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(UTC)
            task_results[task.name] = task.result

        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = str(exc)
            task.completed_at = datetime.now(UTC)
            raise TaskExecutionError(task.name, str(exc)) from exc

    async def _fan_out(self, task: Task, count: int) -> list[Any]:
        """Execute a task across multiple agents in parallel."""
        attempts = [self._clone_task(task) for _ in range(count)]
        coros = [self.executor(attempt) for attempt in attempts]
        results = await asyncio.gather(*coros, return_exceptions=True)

        task.cost = 0.0
        successes = [r for r in results if not isinstance(r, BaseException)]
        for attempt, outcome in zip(attempts, results, strict=True):
            task.cost += attempt.cost
            if isinstance(outcome, BaseException):
                continue

        if not successes:
            raise TaskExecutionError(
                task.name,
                f"All {count} fan-out executions failed",
            )
        return successes

    def _fan_in(
        self,
        results: list[Any],
        strategy: FanInStrategy,
    ) -> Any:
        """Merge fan-out results according to the given strategy."""
        if strategy == FanInStrategy.FIRST:
            return results[0]

        if strategy == FanInStrategy.VOTE:
            from collections import Counter

            counted: dict[Any, int] = Counter(str(r) for r in results)
            winner = max(counted, key=lambda k: counted[k])
            return next(r for r in results if str(r) == winner)

        # Default: merge into a list
        return results

    async def _consensus(
        self,
        task: Task,
        config: ConsensusConfig,
    ) -> Any:
        """Execute a task with multiple agents and check for consensus."""
        attempts = [self._clone_task(task) for _ in range(config.agents)]
        coros = [self.executor(attempt) for attempt in attempts]
        results = await asyncio.gather(*coros, return_exceptions=True)

        task.cost = 0.0
        successes = [r for r in results if not isinstance(r, BaseException)]
        for attempt in attempts:
            task.cost += attempt.cost

        if config.threshold == ConsensusThreshold.ALL_AGREE:
            str_results = [str(r) for r in successes]
            if len(set(str_results)) == 1 and len(successes) == config.agents:
                return successes[0]
            raise ConsensusNotReachedError(task.name, len(successes), config.agents)

        if config.threshold == ConsensusThreshold.MAJORITY:
            from collections import Counter

            counted = Counter(str(r) for r in successes)
            most_common = counted.most_common(1)
            if most_common and most_common[0][1] > config.agents / 2:
                winner = most_common[0][0]
                return next(r for r in successes if str(r) == winner)
            raise ConsensusNotReachedError(task.name, 0, config.agents)

        if config.threshold == ConsensusThreshold.ANY:
            if successes:
                return successes[0]
            raise ConsensusNotReachedError(task.name, 0, config.agents)

        return successes[0] if successes else None

    def _clone_task(self, task: Task) -> Task:
        """Create an isolated copy of a task for parallel execution."""
        return copy.deepcopy(task)

    def _inject_dependencies(
        self,
        task: Task,
        task_results: dict[str, Any],
    ) -> Task:
        """Inject upstream task results into a dependent task's input."""
        if not task.depends_on:
            return task

        upstream_results = {
            dep: task_results[dep] for dep in task.depends_on if dep in task_results
        }

        if len(task.depends_on) == 1:
            dep_name = task.depends_on[0]
            if dep_name in upstream_results and task.input is None:
                task.input = upstream_results[dep_name]
        else:
            if task.input is None:
                task.input = upstream_results
            elif isinstance(task.input, dict):
                task.input = {**upstream_results, **task.input}

        return task

    def _topological_sort(self, workflow: Workflow) -> list[Task]:
        """Topologically sort tasks by their dependencies.

        Raises:
            CyclicDependencyError: If the graph contains a cycle.
        """
        task_map: dict[str, Task] = {t.name: t for t in workflow.tasks}
        in_degree: dict[str, int] = defaultdict(int)
        graph: dict[str, list[str]] = defaultdict(list)

        for task in workflow.tasks:
            if task.name not in in_degree:
                in_degree[task.name] = 0
            for dep in task.depends_on:
                graph[dep].append(task.name)
                in_degree[task.name] += 1

        queue = [name for name, deg in in_degree.items() if deg == 0]
        result: list[Task] = []

        while queue:
            name = queue.pop(0)
            result.append(task_map[name])
            for child in graph[name]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(result) != len(workflow.tasks):
            visited = {t.name for t in result}
            cycle = [t.name for t in workflow.tasks if t.name not in visited]
            raise CyclicDependencyError(cycle)

        return result

    def _build_levels(
        self,
        sorted_tasks: list[Task],
        workflow: Workflow,
    ) -> list[list[Task]]:
        """Group topologically sorted tasks into concurrency levels.

        Tasks at the same level have no mutual dependencies and can run
        in parallel.
        """
        completed: set[str] = set()
        levels: list[list[Task]] = []
        remaining = list(sorted_tasks)

        while remaining:
            level: list[Task] = []
            next_remaining: list[Task] = []

            for task in remaining:
                deps_met = all(d in completed for d in task.depends_on)
                if deps_met:
                    level.append(task)
                else:
                    next_remaining.append(task)

            if not level:
                # Should not happen after topo-sort, but be safe
                break

            levels.append(level)
            for task in level:
                completed.add(task.name)
            remaining = next_remaining

        return levels
