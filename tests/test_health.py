"""Tests for agent health score degradation."""

from __future__ import annotations

from a2a_mesh.health import HealthScorer
from a2a_mesh.models import (
    AgentCard,
    RegisteredAgent,
    RoutingPolicy,
    RoutingStrategy,
    Task,
)
from a2a_mesh.registry import AgentRegistry
from a2a_mesh.router import Router


class TestHealthScorer:
    """Tests for the HealthScorer class."""

    def _make_agent(self, name: str = "agent-a") -> RegisteredAgent:
        return RegisteredAgent(card=AgentCard(name=name, capabilities=["work"]))

    def test_initial_score_is_one(self) -> None:
        agent = self._make_agent()
        scorer = HealthScorer()
        assert scorer.score(agent) == 1.0

    def test_success_keeps_score_high(self) -> None:
        agent = self._make_agent()
        scorer = HealthScorer()
        for _ in range(5):
            scorer.record_success(agent, latency_ms=100.0)
        assert agent.health_score >= 0.99

    def test_failure_degrades_score(self) -> None:
        agent = self._make_agent()
        scorer = HealthScorer()
        scorer.record_failure(agent)
        assert agent.health_score < 1.0
        assert agent.total_failures == 1
        assert agent.total_requests == 1

    def test_multiple_failures_degrade_further(self) -> None:
        agent = self._make_agent()
        scorer = HealthScorer()
        scores = []
        for _ in range(5):
            scorer.record_failure(agent)
            scores.append(agent.health_score)
        # Score should monotonically decrease
        for i in range(1, len(scores)):
            assert scores[i] < scores[i - 1]

    def test_score_recovers_after_successes(self) -> None:
        agent = self._make_agent()
        scorer = HealthScorer()
        # Degrade
        for _ in range(3):
            scorer.record_failure(agent)
        degraded = agent.health_score
        # Recover
        for _ in range(20):
            scorer.record_success(agent, latency_ms=50.0)
        assert agent.health_score > degraded

    def test_score_never_goes_below_zero(self) -> None:
        agent = self._make_agent()
        scorer = HealthScorer()
        for _ in range(100):
            scorer.record_failure(agent)
        assert agent.health_score >= 0.0

    def test_score_never_exceeds_one(self) -> None:
        agent = self._make_agent()
        scorer = HealthScorer()
        for _ in range(100):
            scorer.record_success(agent, latency_ms=10.0)
        assert agent.health_score <= 1.0

    def test_high_latency_applies_penalty(self) -> None:
        agent = self._make_agent()
        scorer = HealthScorer(latency_threshold_ms=100.0)
        scorer.record_success(agent, latency_ms=500.0)
        assert agent.health_score < 1.0

    def test_request_counts_tracked(self) -> None:
        agent = self._make_agent()
        scorer = HealthScorer()
        scorer.record_success(agent)
        scorer.record_success(agent)
        scorer.record_failure(agent)
        assert agent.total_requests == 3
        assert agent.total_failures == 1


class TestHealthScoreRouting:
    """Tests that health scores influence routing decisions."""

    def test_health_score_strategy_prefers_healthy_agent(self) -> None:
        registry = AgentRegistry(health_interval=600.0)
        for name in ("healthy", "degraded", "sick"):
            registry.register(
                AgentCard(name=name, capabilities=["compute"])
            )
        registry.agents["healthy"].health_score = 0.95
        registry.agents["degraded"].health_score = 0.50
        registry.agents["sick"].health_score = 0.10

        policy = RoutingPolicy(strategy=RoutingStrategy.HEALTH_SCORE)
        router = Router(registry, policy=policy)

        task = Task(name="t", required_capabilities=["compute"])
        selected = router.route(task)
        assert selected.card.name == "healthy"

    def test_health_score_multi_sorts_descending(self) -> None:
        registry = AgentRegistry(health_interval=600.0)
        for name, score in [("a", 0.3), ("b", 0.9), ("c", 0.6)]:
            registry.register(AgentCard(name=name, capabilities=["work"]))
            registry.agents[name].health_score = score

        policy = RoutingPolicy(strategy=RoutingStrategy.HEALTH_SCORE)
        router = Router(registry, policy=policy)
        task = Task(name="t", required_capabilities=["work"])
        selected = router.route_multi(task, count=3)
        scores = [a.health_score for a in selected]
        assert scores == sorted(scores, reverse=True)
