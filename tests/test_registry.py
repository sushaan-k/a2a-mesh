"""Tests for the agent registry."""

from __future__ import annotations

import httpx
import pytest
import respx

from a2a_mesh.exceptions import AgentAlreadyRegisteredError, AgentNotFoundError
from a2a_mesh.models import AgentCard, AgentStatus
from a2a_mesh.registry import AgentRegistry, RedisAgentRegistry


class FakeRedisClient:
    """Minimal Redis-like client for registry persistence tests."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.closed = False

    def ping(self) -> bool:
        return True

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    def hset(self, key: str, field: str, value: str) -> int:
        self.hashes.setdefault(key, {})[field] = value
        return 1

    def hdel(self, key: str, field: str) -> int:
        bucket = self.hashes.get(key, {})
        if field in bucket:
            del bucket[field]
            if not bucket:
                self.hashes.pop(key, None)
            return 1
        return 0

    def close(self) -> None:
        self.closed = True


class TestAgentRegistry:
    """Tests for AgentRegistry."""

    def test_register_agent(
        self, registry: AgentRegistry, research_card: AgentCard
    ) -> None:
        agent = registry.register(research_card)
        assert agent.card.name == "research-agent"
        assert agent.status == AgentStatus.UNKNOWN
        assert "research-agent" in registry.agents

    def test_register_duplicate_raises(
        self, registry: AgentRegistry, research_card: AgentCard
    ) -> None:
        registry.register(research_card)
        with pytest.raises(AgentAlreadyRegisteredError):
            registry.register(research_card)

    def test_register_duplicate_with_force(
        self, registry: AgentRegistry, research_card: AgentCard
    ) -> None:
        agent1 = registry.register(research_card)
        agent2 = registry.register(research_card, force=True)
        assert agent1.agent_id != agent2.agent_id

    def test_deregister_agent(
        self, registry: AgentRegistry, research_card: AgentCard
    ) -> None:
        registry.register(research_card)
        registry.deregister("research-agent")
        assert "research-agent" not in registry.agents

    def test_deregister_unknown_raises(self, registry: AgentRegistry) -> None:
        with pytest.raises(AgentNotFoundError):
            registry.deregister("nonexistent")

    def test_get_agent(self, registry: AgentRegistry, research_card: AgentCard) -> None:
        registry.register(research_card)
        agent = registry.get("research-agent")
        assert agent.card.name == "research-agent"

    def test_get_unknown_raises(self, registry: AgentRegistry) -> None:
        with pytest.raises(AgentNotFoundError):
            registry.get("nonexistent")

    def test_list_agents(self, populated_registry: AgentRegistry) -> None:
        agents = populated_registry.list_agents()
        assert len(agents) == 3
        names = {a.card.name for a in agents}
        assert "research-agent" in names
        assert "analysis-agent" in names
        assert "writing-agent" in names

    def test_find_by_capability(self, populated_registry: AgentRegistry) -> None:
        matches = populated_registry.find_by_capability(
            ["summarization"], healthy_only=False
        )
        # research, analysis, and writing agents all have summarization
        assert len(matches) == 3

    def test_find_by_specific_capability(
        self, populated_registry: AgentRegistry
    ) -> None:
        matches = populated_registry.find_by_capability(
            ["web_search"], healthy_only=False
        )
        assert len(matches) == 1
        assert matches[0].card.name == "research-agent"

    def test_find_by_multiple_capabilities(
        self, populated_registry: AgentRegistry
    ) -> None:
        matches = populated_registry.find_by_capability(
            ["data_analysis", "financial_analysis"], healthy_only=False
        )
        assert len(matches) == 1
        assert matches[0].card.name == "analysis-agent"

    def test_find_no_match(self, populated_registry: AgentRegistry) -> None:
        matches = populated_registry.find_by_capability(
            ["quantum_computing"], healthy_only=False
        )
        assert len(matches) == 0

    def test_find_excludes_unhealthy(self, populated_registry: AgentRegistry) -> None:
        populated_registry.agents["research-agent"].status = AgentStatus.UNHEALTHY
        matches = populated_registry.find_by_capability(
            ["web_search"], healthy_only=True
        )
        assert len(matches) == 0

    def test_find_sorted_by_load(self, populated_registry: AgentRegistry) -> None:
        populated_registry.agents["writing-agent"].current_load = 5
        populated_registry.agents["research-agent"].current_load = 1
        populated_registry.agents["analysis-agent"].current_load = 3
        matches = populated_registry.find_by_capability(
            ["summarization"], healthy_only=False
        )
        loads = [m.current_load for m in matches]
        assert loads == sorted(loads)

    @pytest.mark.asyncio
    async def test_health_check_no_url(self, registry: AgentRegistry) -> None:
        card = AgentCard(name="local-agent")
        registry.register(card)
        status = await registry.check_health("local-agent")
        assert status == AgentStatus.UNKNOWN

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_healthy(self, registry: AgentRegistry) -> None:
        """Agent with URL returning 200 should be marked healthy."""
        respx.get("http://localhost:9001/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        card = AgentCard(
            name="remote-agent",
            url="http://localhost:9001",
            health_endpoint="/health",
        )
        registry.register(card)
        status = await registry.check_health("remote-agent")
        assert status == AgentStatus.HEALTHY
        assert registry.agents["remote-agent"].last_health_check is not None

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_degraded(self, registry: AgentRegistry) -> None:
        """Agent returning 4xx should be marked degraded."""
        respx.get("http://localhost:9002/health").mock(
            return_value=httpx.Response(429, text="Too Many Requests")
        )
        card = AgentCard(
            name="degraded-agent",
            url="http://localhost:9002",
            health_endpoint="/health",
        )
        registry.register(card)
        status = await registry.check_health("degraded-agent")
        assert status == AgentStatus.DEGRADED

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_unhealthy_500(self, registry: AgentRegistry) -> None:
        """Agent returning 500 should be marked unhealthy."""
        respx.get("http://localhost:9003/health").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        card = AgentCard(
            name="unhealthy-agent",
            url="http://localhost:9003",
            health_endpoint="/health",
        )
        registry.register(card)
        status = await registry.check_health("unhealthy-agent")
        assert status == AgentStatus.UNHEALTHY

    @pytest.mark.asyncio
    @respx.mock
    async def test_health_check_connection_error(self, registry: AgentRegistry) -> None:
        """Agent that refuses connections should be marked unhealthy."""
        respx.get("http://localhost:9004/health").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        card = AgentCard(
            name="unreachable-agent",
            url="http://localhost:9004",
            health_endpoint="/health",
        )
        registry.register(card)
        status = await registry.check_health("unreachable-agent")
        assert status == AgentStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_start_stop(self, registry: AgentRegistry) -> None:
        """Registry start/stop lifecycle manages the health task."""
        await registry.start()
        assert registry._health_task is not None
        await registry.stop()
        assert registry._health_task is None
        assert registry._http_client is None

    @pytest.mark.asyncio
    async def test_redis_registry_persists_state(self) -> None:
        client = FakeRedisClient()
        registry = RedisAgentRegistry(
            client=client,
            health_interval=600.0,
            key_prefix="test-mesh",
        )

        card = AgentCard(
            name="shared-agent",
            capabilities=["shared", "summarization"],
            cost_per_task=0.01,
        )
        registry.register(card)
        assert "shared-agent" in client.hashes["test-mesh:agents"]

        registry.agents = {}
        registry.refresh()
        assert registry.get("shared-agent").card.name == "shared-agent"

        matches = registry.find_by_capability(["shared"], healthy_only=False)
        assert [agent.card.name for agent in matches] == ["shared-agent"]

        registry.deregister("shared-agent")
        assert registry.list_agents() == []

        await registry.start()
        assert registry._health_task is not None
        await registry.stop()
        assert client.closed is True
