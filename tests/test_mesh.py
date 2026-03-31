"""Tests for the main Mesh runtime."""

from __future__ import annotations

import httpx
import pytest
import respx

from a2a_mesh.exceptions import NoCapableAgentError
from a2a_mesh.mesh import Mesh
from a2a_mesh.models import (
    AgentCard,
    Task,
    TaskStatus,
    Workflow,
)
from a2a_mesh.registry import AgentRegistry


@pytest.fixture
def mesh() -> Mesh:
    """Create a Mesh instance for testing."""
    return Mesh(port=0, log_level="WARNING", health_interval=600.0)


class TestMeshRegistration:
    """Tests for agent registration via the Mesh."""

    def test_register_agent(self, mesh: Mesh) -> None:
        card = AgentCard(name="agent-a", capabilities=["search"])
        agent = mesh.register(card)
        assert agent.card.name == "agent-a"
        assert "agent-a" in mesh.registry.agents

    def test_register_agent_with_url(self, mesh: Mesh) -> None:
        card = AgentCard(
            name="remote-agent",
            url="http://localhost:9001",
            capabilities=["search"],
        )
        mesh.register(card)
        assert "remote-agent" in mesh._a2a_clients

    def test_register_agent_without_url(self, mesh: Mesh) -> None:
        card = AgentCard(name="local-agent", capabilities=["local"])
        mesh.register(card)
        assert "local-agent" not in mesh._a2a_clients

    def test_deregister_agent(self, mesh: Mesh) -> None:
        card = AgentCard(name="agent-x", capabilities=["test"])
        mesh.register(card)
        mesh.deregister("agent-x")
        assert "agent-x" not in mesh.registry.agents

    def test_register_force_overwrite(self, mesh: Mesh) -> None:
        card = AgentCard(name="agent-a", capabilities=["v1"])
        mesh.register(card)
        card_v2 = AgentCard(name="agent-a", capabilities=["v2"])
        agent = mesh.register(card_v2, force=True)
        assert "v2" in agent.card.capabilities


class TestMeshDispatch:
    """Tests for task dispatch."""

    @pytest.mark.asyncio
    async def test_dispatch_string_task(self, mesh: Mesh) -> None:
        mesh.register(AgentCard(name="echo-agent", capabilities=["echo"]))
        result = await mesh.dispatch("test prompt", required_capabilities=["echo"])
        # No URL, so returns echo response
        assert result["agent"] == "echo-agent"
        assert result["input"] == "test prompt"

    @pytest.mark.asyncio
    async def test_dispatch_task_object(self, mesh: Mesh) -> None:
        mesh.register(AgentCard(name="echo-agent", capabilities=["echo"]))
        task = Task(
            name="explicit",
            input="task data",
            required_capabilities=["echo"],
        )
        result = await mesh.dispatch(task)
        assert result["agent"] == "echo-agent"

    @pytest.mark.asyncio
    async def test_dispatch_no_capable_agent_raises(self, mesh: Mesh) -> None:
        with pytest.raises(NoCapableAgentError):
            await mesh.dispatch(
                "no agent for this",
                required_capabilities=["nonexistent"],
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_dispatch_to_remote_agent(self, mesh: Mesh) -> None:
        respx.post("http://remote-agent.local/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"analysis": "done"},
                },
            )
        )
        mesh.register(
            AgentCard(
                name="remote",
                url="http://remote-agent.local",
                capabilities=["analysis"],
            )
        )
        result = await mesh.dispatch("analyze this", required_capabilities=["analysis"])
        assert result["analysis"] == "done"

    @pytest.mark.asyncio
    @respx.mock
    async def test_dispatch_to_authenticated_remote_agent(self, mesh: Mesh) -> None:
        route = respx.post("http://secure-agent.local/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"analysis": "done"},
                },
            )
        )
        mesh.register(
            AgentCard(
                name="secure",
                url="http://secure-agent.local",
                capabilities=["analysis"],
                auth_required=True,
            )
        )
        result = await mesh.dispatch("analyze this", required_capabilities=["analysis"])
        assert result["analysis"] == "done"
        assert route.calls
        auth_header = route.calls[0].request.headers["authorization"]
        assert auth_header.startswith("Bearer ")
        claims = mesh.auth.validate_token(auth_header.removeprefix("Bearer "))
        assert claims["sub"] == "secure"

    @pytest.mark.asyncio
    async def test_dispatch_creates_trace(self, mesh: Mesh) -> None:
        mesh.register(AgentCard(name="traced", capabilities=["tracing"]))
        await mesh.dispatch("trace me", required_capabilities=["tracing"])
        spans = mesh.tracer.get_traces()
        assert len(spans) >= 1
        ops = [s.operation for s in spans]
        assert "dispatch" in ops


class TestMeshWorkflow:
    """Tests for workflow execution via the Mesh."""

    @pytest.mark.asyncio
    async def test_execute_workflow(self, mesh: Mesh) -> None:
        mesh.register(AgentCard(name="step-agent", capabilities=["step"]))
        workflow = Workflow(
            name="test-wf",
            tasks=[
                Task(name="step1", agent="step-agent", input="data"),
                Task(
                    name="step2",
                    agent="step-agent",
                    depends_on=["step1"],
                ),
            ],
        )
        result = await mesh.execute_workflow(workflow)
        assert result.status == TaskStatus.COMPLETED
        assert "step1" in result.task_results
        assert "step2" in result.task_results


class TestMeshObservability:
    """Tests for observability features."""

    def test_traces_empty(self, mesh: Mesh) -> None:
        traces = mesh.traces()
        assert traces == []

    @pytest.mark.asyncio
    async def test_traces_after_dispatch(self, mesh: Mesh) -> None:
        mesh.register(AgentCard(name="obs-agent", capabilities=["obs"]))
        await mesh.dispatch("observe", required_capabilities=["obs"])
        traces = mesh.traces(limit=10)
        assert len(traces) >= 1


class TestMeshLifecycle:
    """Tests for mesh start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_stop(self, mesh: Mesh) -> None:
        await mesh.start()
        await mesh.stop()

    @pytest.mark.asyncio
    async def test_stop_cleans_up_clients(self, mesh: Mesh) -> None:
        mesh.register(
            AgentCard(
                name="r",
                url="http://localhost:1234",
                capabilities=["x"],
            )
        )
        await mesh.start()
        await mesh.stop()
        assert len(mesh._a2a_clients) == 0

    def test_serve_wires_auth_and_host(
        self, mesh: Mesh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        def fake_create_gateway(*args: object, **kwargs: object) -> object:
            captured["create_gateway_args"] = args
            captured["create_gateway_kwargs"] = kwargs
            return object()

        def fake_run(app: object, *, host: str, port: int) -> None:
            captured["run_app"] = app
            captured["run_host"] = host
            captured["run_port"] = port

        monkeypatch.setattr("a2a_mesh.gateway.create_gateway", fake_create_gateway)
        monkeypatch.setattr("a2a_mesh.mesh.uvicorn.run", fake_run)

        mesh.serve(host="0.0.0.0")

        assert captured["create_gateway_kwargs"]["auth_manager"] is mesh.auth
        assert captured["create_gateway_kwargs"]["on_startup"] == [mesh.start]
        assert captured["run_host"] == "0.0.0.0"
        assert captured["run_port"] == mesh.port

    def test_mesh_can_use_custom_registry(self) -> None:
        registry = AgentRegistry(health_interval=600.0)
        mesh = Mesh(port=0, log_level="WARNING", registry=registry)
        assert mesh.registry is registry

    def test_mesh_uses_redis_registry_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        class FakeRedisRegistry(AgentRegistry):
            def __init__(self, redis_url: str, health_interval: float) -> None:
                super().__init__(health_interval=health_interval)
                captured["redis_url"] = redis_url

        monkeypatch.setattr("a2a_mesh.mesh.RedisAgentRegistry", FakeRedisRegistry)

        mesh = Mesh(
            port=0,
            log_level="WARNING",
            health_interval=12.0,
            redis_url="redis://example.local/1",
        )

        assert isinstance(mesh.registry, FakeRedisRegistry)
        assert captured["redis_url"] == "redis://example.local/1"
