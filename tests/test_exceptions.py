"""Tests for custom exception classes."""

from __future__ import annotations

from a2a_mesh.exceptions import (
    AgentAlreadyRegisteredError,
    AgentNotFoundError,
    AuthError,
    ConsensusNotReachedError,
    CyclicDependencyError,
    HealthCheckFailedError,
    InsufficientScopeError,
    JsonRpcError,
    MeshError,
    NoCapableAgentError,
    ProtocolError,
    QueueFullError,
    RoutingError,
    TaskExecutionError,
    TokenExpiredError,
    WorkflowError,
)


class TestExceptionHierarchy:
    """Tests that exception hierarchy is correct."""

    def test_mesh_error_is_base(self) -> None:
        assert issubclass(MeshError, Exception)

    def test_registry_errors(self) -> None:
        assert issubclass(AgentNotFoundError, MeshError)
        assert issubclass(AgentAlreadyRegisteredError, MeshError)
        assert issubclass(HealthCheckFailedError, MeshError)

    def test_routing_errors(self) -> None:
        assert issubclass(RoutingError, MeshError)
        assert issubclass(NoCapableAgentError, MeshError)
        assert issubclass(QueueFullError, RoutingError)

    def test_workflow_errors(self) -> None:
        assert issubclass(WorkflowError, MeshError)
        assert issubclass(CyclicDependencyError, WorkflowError)
        assert issubclass(TaskExecutionError, WorkflowError)
        assert issubclass(ConsensusNotReachedError, WorkflowError)

    def test_auth_errors(self) -> None:
        assert issubclass(AuthError, MeshError)
        assert issubclass(TokenExpiredError, AuthError)
        assert issubclass(InsufficientScopeError, AuthError)

    def test_protocol_errors(self) -> None:
        assert issubclass(ProtocolError, MeshError)
        assert issubclass(JsonRpcError, ProtocolError)


class TestExceptionMessages:
    """Tests that exception messages are informative."""

    def test_agent_not_found(self) -> None:
        exc = AgentNotFoundError("my-agent")
        assert "my-agent" in str(exc)
        assert exc.agent_name == "my-agent"
        assert exc.detail

    def test_agent_already_registered(self) -> None:
        exc = AgentAlreadyRegisteredError("my-agent")
        assert "my-agent" in str(exc)

    def test_health_check_failed(self) -> None:
        exc = HealthCheckFailedError("my-agent", "timeout")
        assert "my-agent" in str(exc)
        assert "timeout" in str(exc)

    def test_no_capable_agent(self) -> None:
        exc = NoCapableAgentError(["search", "analyze"])
        assert "search" in str(exc)
        assert exc.capabilities == ["search", "analyze"]

    def test_queue_full(self) -> None:
        exc = QueueFullError("busy-agent", 50)
        assert "busy-agent" in str(exc)
        assert "50" in str(exc)

    def test_cyclic_dependency(self) -> None:
        exc = CyclicDependencyError(["a", "b", "c"])
        assert "a" in str(exc)
        assert exc.cycle == ["a", "b", "c"]

    def test_task_execution(self) -> None:
        exc = TaskExecutionError("my-task", "agent crashed")
        assert "my-task" in str(exc)
        assert exc.task_name == "my-task"

    def test_consensus_not_reached(self) -> None:
        exc = ConsensusNotReachedError("review", 1, 3)
        assert "review" in str(exc)
        assert exc.received == 1
        assert exc.required == 3

    def test_token_expired(self) -> None:
        exc = TokenExpiredError()
        assert "expired" in str(exc).lower()

    def test_insufficient_scope(self) -> None:
        exc = InsufficientScopeError(required=["write"], provided=["read"])
        assert "write" in str(exc)
        assert exc.required == ["write"]
        assert exc.provided == ["read"]

    def test_jsonrpc_error(self) -> None:
        exc = JsonRpcError(-32603, "Internal error")
        assert "-32603" in str(exc)
        assert exc.code == -32603

    def test_mesh_error_detail(self) -> None:
        exc = MeshError("something broke", detail="check logs")
        assert exc.detail == "check logs"
        assert str(exc) == "something broke"
