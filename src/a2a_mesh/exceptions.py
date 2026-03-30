"""Custom exception classes for a2a-mesh.

Provides a structured exception hierarchy so callers can catch errors at the
appropriate level of granularity.
"""

from __future__ import annotations


class MeshError(Exception):
    """Base exception for all a2a-mesh errors."""

    def __init__(self, message: str = "", *, detail: str = "") -> None:
        self.detail = detail
        super().__init__(message)


# ---------------------------------------------------------------------------
# Registry errors
# ---------------------------------------------------------------------------


class AgentNotFoundError(MeshError):
    """Raised when a requested agent is not registered in the mesh."""

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        super().__init__(
            f"Agent not found: {agent_name!r}",
            detail="Check that the agent is registered and healthy.",
        )


class AgentAlreadyRegisteredError(MeshError):
    """Raised when trying to register an agent that already exists."""

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        super().__init__(
            f"Agent already registered: {agent_name!r}",
            detail="Use force=True to re-register or deregister first.",
        )


class HealthCheckFailedError(MeshError):
    """Raised when an agent's health check fails."""

    def __init__(self, agent_name: str, reason: str = "") -> None:
        self.agent_name = agent_name
        super().__init__(
            f"Health check failed for agent {agent_name!r}: {reason}",
            detail="The agent may be down or unreachable.",
        )


# ---------------------------------------------------------------------------
# Routing errors
# ---------------------------------------------------------------------------


class NoCapableAgentError(MeshError):
    """Raised when no agent matches the required capabilities."""

    def __init__(self, capabilities: list[str]) -> None:
        self.capabilities = capabilities
        super().__init__(
            f"No agent found with capabilities: {capabilities}",
            detail="Register an agent with the required capabilities.",
        )


class RoutingError(MeshError):
    """Raised when task routing fails for any reason."""


class QueueFullError(RoutingError):
    """Raised when all capable agents have full task queues."""

    def __init__(self, agent_name: str, depth: int) -> None:
        self.agent_name = agent_name
        super().__init__(
            f"Queue full for agent {agent_name!r} (depth={depth})",
            detail="Wait for tasks to complete or increase max_queue_depth.",
        )


# ---------------------------------------------------------------------------
# Workflow / coordination errors
# ---------------------------------------------------------------------------


class WorkflowError(MeshError):
    """Raised when workflow execution encounters an error."""


class CyclicDependencyError(WorkflowError):
    """Raised when a workflow DAG contains a cycle."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__(
            f"Cyclic dependency detected: {' -> '.join(cycle)}",
            detail="Workflows must be directed acyclic graphs.",
        )


class TaskExecutionError(WorkflowError):
    """Raised when a task within a workflow fails."""

    def __init__(self, task_name: str, reason: str = "") -> None:
        self.task_name = task_name
        super().__init__(
            f"Task {task_name!r} failed: {reason}",
        )


class ConsensusNotReachedError(WorkflowError):
    """Raised when agents cannot reach consensus on a task result."""

    def __init__(self, task_name: str, received: int, required: int) -> None:
        self.task_name = task_name
        self.received = received
        self.required = required
        super().__init__(
            f"Consensus not reached for {task_name!r}: "
            f"{received}/{required} agents agreed",
        )


# ---------------------------------------------------------------------------
# Auth errors
# ---------------------------------------------------------------------------


class AuthError(MeshError):
    """Raised when authentication or authorization fails."""


class TokenExpiredError(AuthError):
    """Raised when a JWT token has expired."""

    def __init__(self) -> None:
        super().__init__("Token has expired")


class InsufficientScopeError(AuthError):
    """Raised when a token lacks the required scopes."""

    def __init__(self, required: list[str], provided: list[str]) -> None:
        self.required = required
        self.provided = provided
        super().__init__(
            f"Insufficient scopes: required={required}, provided={provided}",
        )


# ---------------------------------------------------------------------------
# Protocol errors
# ---------------------------------------------------------------------------


class ProtocolError(MeshError):
    """Raised when an A2A or MCP protocol-level error occurs."""


class JsonRpcError(ProtocolError):
    """Raised for JSON-RPC protocol errors."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"JSON-RPC error {code}: {message}")
