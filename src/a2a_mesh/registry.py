"""Agent Registry for a2a-mesh.

The registry is the service-discovery backbone of the mesh. Agents register
their Agent Cards, and the registry provides capability-based lookup, health
monitoring, and version management.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

from a2a_mesh._logging import get_logger
from a2a_mesh.exceptions import (
    AgentAlreadyRegisteredError,
    AgentNotFoundError,
    HealthCheckFailedError,
)
from a2a_mesh.models import AgentCard, AgentStatus, RegisteredAgent

logger = get_logger(__name__)


def _serialize_agent(agent: RegisteredAgent) -> str:
    """Serialize a registered agent for persistence."""
    return json.dumps(agent.model_dump(mode="json"))


def _deserialize_agent(payload: str) -> RegisteredAgent:
    """Deserialize a persisted registered agent."""
    return RegisteredAgent.model_validate_json(payload)


def _load_redis_client(redis_url: str) -> Any:
    """Create a synchronous Redis client without importing redis eagerly."""
    try:
        import redis
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised in docs
        raise RuntimeError(
            "Redis support requires the optional 'redis' dependency."
        ) from exc

    return redis.Redis.from_url(redis_url, decode_responses=True)


class AgentRegistry:
    """In-memory agent registry with health monitoring.

    The registry stores agent cards, tracks health status, and supports
    capability-based discovery. A background health-check loop periodically
    pings registered agents and marks unhealthy ones.

    Attributes:
        agents: Mapping of agent name to its registered state.
        health_interval: Seconds between health check sweeps.
    """

    def __init__(self, health_interval: float = 30.0) -> None:
        """Initialize the registry.

        Args:
            health_interval: Seconds between health check sweeps.
        """
        self.agents: dict[str, RegisteredAgent] = {}
        self.health_interval = health_interval
        self._health_task: asyncio.Task[None] | None = None
        self._http_client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Start the background health-check loop."""
        self._http_client = httpx.AsyncClient(timeout=5.0)
        self._health_task = asyncio.create_task(self._health_loop())
        logger.info("registry.started", health_interval=self.health_interval)

    async def stop(self) -> None:
        """Stop the health-check loop and clean up resources."""
        if self._health_task is not None:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task
            self._health_task = None
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("registry.stopped")

    def register(self, card: AgentCard, *, force: bool = False) -> RegisteredAgent:
        """Register an agent with the mesh.

        Args:
            card: The agent's capability card.
            force: If True, overwrite an existing registration.

        Returns:
            The registered agent record.

        Raises:
            AgentAlreadyRegisteredError: If the agent is already registered
                and force is False.
        """
        if card.name in self.agents and not force:
            raise AgentAlreadyRegisteredError(card.name)

        agent = RegisteredAgent(card=card, status=AgentStatus.UNKNOWN)
        self.agents[card.name] = agent
        logger.info(
            "agent.registered",
            agent=card.name,
            capabilities=card.capabilities,
            version=card.version,
        )
        return agent

    def deregister(self, agent_name: str) -> None:
        """Remove an agent from the registry.

        Args:
            agent_name: Name of the agent to remove.

        Raises:
            AgentNotFoundError: If the agent is not registered.
        """
        if agent_name not in self.agents:
            raise AgentNotFoundError(agent_name)
        del self.agents[agent_name]
        logger.info("agent.deregistered", agent=agent_name)

    def get(self, agent_name: str) -> RegisteredAgent:
        """Retrieve a registered agent by name.

        Args:
            agent_name: Name of the agent.

        Returns:
            The registered agent record.

        Raises:
            AgentNotFoundError: If the agent is not registered.
        """
        if agent_name not in self.agents:
            raise AgentNotFoundError(agent_name)
        return self.agents[agent_name]

    def find_by_capability(
        self,
        capabilities: Sequence[str],
        *,
        healthy_only: bool = True,
    ) -> list[RegisteredAgent]:
        """Find agents that support all of the given capabilities.

        Args:
            capabilities: Required capability tags.
            healthy_only: If True, exclude unhealthy agents.

        Returns:
            List of matching registered agents, sorted by current load
            (ascending).
        """
        required = set(capabilities)
        matches: list[RegisteredAgent] = []

        for agent in self.agents.values():
            agent_caps = set(agent.card.capabilities)
            if not required.issubset(agent_caps):
                continue
            if healthy_only and agent.status == AgentStatus.UNHEALTHY:
                continue
            matches.append(agent)

        matches.sort(key=lambda a: a.current_load)
        return matches

    def list_agents(self) -> list[RegisteredAgent]:
        """Return all registered agents.

        Returns:
            List of all registered agents.
        """
        return list(self.agents.values())

    async def check_health(self, agent_name: str) -> AgentStatus:
        """Run a health check against a single agent.

        Args:
            agent_name: Name of the agent to check.

        Returns:
            The updated health status.

        Raises:
            AgentNotFoundError: If the agent is not registered.
        """
        agent = self.get(agent_name)
        card = agent.card
        if not card.url:
            agent.status = AgentStatus.UNKNOWN
            return agent.status

        url = card.url.rstrip("/") + card.health_endpoint
        try:
            if self._http_client is not None:
                resp = await self._http_client.get(url)
            else:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(url)
            if resp.status_code == 200:
                agent.status = AgentStatus.HEALTHY
            elif resp.status_code < 500:
                agent.status = AgentStatus.DEGRADED
            else:
                agent.status = AgentStatus.UNHEALTHY
        except httpx.HTTPError:
            agent.status = AgentStatus.UNHEALTHY

        agent.last_health_check = datetime.now(UTC)
        logger.debug(
            "health.checked",
            agent=agent_name,
            status=agent.status.value,
        )
        return agent.status

    async def _health_loop(self) -> None:
        """Periodically check health of all registered agents."""
        while True:
            await asyncio.sleep(self.health_interval)
            for name in list(self.agents.keys()):
                try:
                    await self.check_health(name)
                except (AgentNotFoundError, HealthCheckFailedError):
                    pass
                except Exception:
                    logger.exception("health.loop_error", agent=name)


class RedisAgentRegistry(AgentRegistry):
    """Redis-backed agent registry with in-memory read cache.

    The registry stores the serialized agent records in Redis so multiple mesh
    instances can share discovery state. The local ``agents`` cache is refreshed
    on reads and before health sweeps so the synchronous API stays compatible
    with the in-memory registry.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        health_interval: float = 30.0,
        *,
        client: Any | None = None,
        key_prefix: str = "a2a-mesh",
    ) -> None:
        super().__init__(health_interval=health_interval)
        self.key_prefix = key_prefix.rstrip(":")
        self._redis = client or _load_redis_client(redis_url)

    @property
    def _agents_key(self) -> str:
        return f"{self.key_prefix}:agents"

    def refresh(self) -> None:
        """Reload the in-memory cache from Redis."""
        raw_agents = self._redis.hgetall(self._agents_key)
        agents: dict[str, RegisteredAgent] = {}
        for name, payload in raw_agents.items():
            if not payload:
                continue
            try:
                agents[name] = _deserialize_agent(payload)
            except Exception:
                logger.exception("registry.redis_deserialize_failed", agent=name)
        self.agents = agents

    def _write_agent(self, agent: RegisteredAgent) -> None:
        self._redis.hset(self._agents_key, agent.card.name, _serialize_agent(agent))

    def _delete_agent(self, agent_name: str) -> None:
        self._redis.hdel(self._agents_key, agent_name)

    async def start(self) -> None:
        """Start health monitoring after confirming Redis is reachable."""
        self._redis.ping()
        self.refresh()
        await super().start()

    async def stop(self) -> None:
        """Stop monitoring and close the Redis client if it supports close()."""
        await super().stop()
        close = getattr(self._redis, "close", None)
        if callable(close):
            close()

    def register(self, card: AgentCard, *, force: bool = False) -> RegisteredAgent:
        self.refresh()
        if card.name in self.agents and not force:
            raise AgentAlreadyRegisteredError(card.name)

        agent = RegisteredAgent(card=card, status=AgentStatus.UNKNOWN)
        self.agents[card.name] = agent
        self._write_agent(agent)
        logger.info(
            "agent.registered",
            agent=card.name,
            capabilities=card.capabilities,
            version=card.version,
        )
        return agent

    def deregister(self, agent_name: str) -> None:
        self.refresh()
        if agent_name not in self.agents:
            raise AgentNotFoundError(agent_name)
        del self.agents[agent_name]
        self._delete_agent(agent_name)
        logger.info("agent.deregistered", agent=agent_name)

    def get(self, agent_name: str) -> RegisteredAgent:
        self.refresh()
        return super().get(agent_name)

    def find_by_capability(
        self,
        capabilities: Sequence[str],
        *,
        healthy_only: bool = True,
    ) -> list[RegisteredAgent]:
        self.refresh()
        return super().find_by_capability(
            capabilities,
            healthy_only=healthy_only,
        )

    def list_agents(self) -> list[RegisteredAgent]:
        self.refresh()
        return super().list_agents()

    async def check_health(self, agent_name: str) -> AgentStatus:
        status = await super().check_health(agent_name)
        agent = self.agents.get(agent_name)
        if agent is not None:
            self._write_agent(agent)
        return status

    async def _health_loop(self) -> None:
        """Refresh shared state before each sweep so multiple nodes converge."""
        while True:
            await asyncio.sleep(self.health_interval)
            self.refresh()
            for name in list(self.agents.keys()):
                try:
                    await self.check_health(name)
                except (AgentNotFoundError, HealthCheckFailedError):
                    pass
                except Exception:
                    logger.exception("health.loop_error", agent=name)
