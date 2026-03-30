"""Tests for core data models."""

from __future__ import annotations

import pytest

from a2a_mesh.models import (
    AgentCard,
    AgentStatus,
    ConsensusConfig,
    ConsensusThreshold,
    FanInStrategy,
    RegisteredAgent,
    RoutingPolicy,
    RoutingStrategy,
    ScopedToken,
    SpanRecord,
    Task,
    TaskStatus,
    Workflow,
    WorkflowResult,
)


class TestAgentCard:
    """Tests for AgentCard model."""

    def test_minimal_card(self) -> None:
        card = AgentCard(name="test-agent")
        assert card.name == "test-agent"
        assert card.capabilities == []
        assert card.max_concurrent == 10
        assert card.cost_per_task == 0.0

    def test_full_card(self) -> None:
        card = AgentCard(
            name="research",
            description="Web researcher",
            url="http://localhost:9001",
            capabilities=["web_search", "summarization"],
            input_formats=["text/plain"],
            output_formats=["application/json"],
            version="2.0.0",
            max_concurrent=5,
            cost_per_task=0.03,
            health_endpoint="/healthz",
            auth_required=True,
            metadata={"model": "gpt-4"},
        )
        assert card.version == "2.0.0"
        assert card.auth_required is True
        assert "web_search" in card.capabilities
        assert card.metadata["model"] == "gpt-4"

    def test_default_formats(self) -> None:
        card = AgentCard(name="test")
        assert "text/plain" in card.input_formats
        assert "application/json" in card.output_formats


class TestRegisteredAgent:
    """Tests for RegisteredAgent model."""

    def test_defaults(self) -> None:
        card = AgentCard(name="test")
        agent = RegisteredAgent(card=card)
        assert agent.status == AgentStatus.UNKNOWN
        assert agent.current_load == 0
        assert agent.avg_latency_ms == 0.0
        assert agent.agent_id  # auto-generated

    def test_unique_ids(self) -> None:
        card = AgentCard(name="test")
        a1 = RegisteredAgent(card=card)
        a2 = RegisteredAgent(card=card)
        assert a1.agent_id != a2.agent_id


class TestTask:
    """Tests for Task model."""

    def test_defaults(self) -> None:
        task = Task(name="my-task")
        assert task.status == TaskStatus.PENDING
        assert task.depends_on == []
        assert task.result is None
        assert task.cost == 0.0

    def test_with_dependencies(self) -> None:
        task = Task(
            name="analyze",
            agent="analysis-agent",
            depends_on=["research", "fetch"],
            input="data here",
        )
        assert len(task.depends_on) == 2
        assert task.agent == "analysis-agent"

    @pytest.mark.parametrize("status", list(TaskStatus))
    def test_all_statuses(self, status: TaskStatus) -> None:
        task = Task(name="t", status=status)
        assert task.status == status


class TestRoutingPolicy:
    """Tests for RoutingPolicy model."""

    def test_defaults(self) -> None:
        policy = RoutingPolicy()
        assert policy.strategy == RoutingStrategy.ROUND_ROBIN
        assert policy.max_queue_depth == 100

    @pytest.mark.parametrize("strategy", list(RoutingStrategy))
    def test_all_strategies(self, strategy: RoutingStrategy) -> None:
        policy = RoutingPolicy(strategy=strategy)
        assert policy.strategy == strategy


class TestWorkflow:
    """Tests for Workflow model."""

    def test_empty_workflow(self) -> None:
        wf = Workflow(name="empty")
        assert wf.tasks == []
        assert wf.fan_out == {}

    def test_with_fan_out(self) -> None:
        wf = Workflow(
            name="test",
            tasks=[Task(name="research", input="topic")],
            fan_out={"research": 3},
            fan_in={"research": FanInStrategy.MERGE},
        )
        assert wf.fan_out["research"] == 3
        assert wf.fan_in["research"] == FanInStrategy.MERGE


class TestConsensusConfig:
    """Tests for ConsensusConfig model."""

    def test_defaults(self) -> None:
        cfg = ConsensusConfig()
        assert cfg.agents == 2
        assert cfg.threshold == ConsensusThreshold.ALL_AGREE


class TestWorkflowResult:
    """Tests for WorkflowResult model."""

    def test_defaults(self) -> None:
        result = WorkflowResult(workflow_id="abc")
        assert result.status == TaskStatus.COMPLETED
        assert result.total_cost == 0.0
        assert result.errors == {}


class TestScopedToken:
    """Tests for ScopedToken model."""

    def test_creation(self) -> None:
        token = ScopedToken(
            token="jwt.string.here",
            issuer="agent-a",
            subject="agent-b",
            scopes=["read", "write"],
        )
        assert token.issuer == "agent-a"
        assert "read" in token.scopes


class TestSpanRecord:
    """Tests for SpanRecord model."""

    def test_creation(self) -> None:
        span = SpanRecord(operation="dispatch", agent_name="test")
        assert span.status == "ok"
        assert span.cost == 0.0
        assert span.trace_id  # auto-generated
