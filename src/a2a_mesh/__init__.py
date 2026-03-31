"""a2a-mesh: Lightweight multi-agent coordination runtime.

A minimal runtime for multi-agent systems using the A2A protocol.
Handles discovery, routing, coordination, fault tolerance, and
observability for agent-to-agent communication.

Usage::

    from a2a_mesh import Mesh, AgentCard, Workflow, Task

    mesh = Mesh(port=8080)
    mesh.register(AgentCard(name="research", capabilities=["web_search"]))
    result = await mesh.dispatch("Find recent AI papers")
"""

from a2a_mesh.auth import AuthManager
from a2a_mesh.coordinator import WorkflowCoordinator
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
from a2a_mesh.health import HealthScorer
from a2a_mesh.mesh import Mesh
from a2a_mesh.models import (
    AgentCard,
    AgentStatus,
    AuditEntry,
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
from a2a_mesh.protocol.a2a import ErrorCode
from a2a_mesh.registry import AgentRegistry, RedisAgentRegistry
from a2a_mesh.router import Router
from a2a_mesh.tracer import MeshTracer

__version__ = "0.1.0"

__all__ = [
    # Core runtime
    "Mesh",
    # Models
    "AgentCard",
    "AgentStatus",
    "AuditEntry",
    "ConsensusConfig",
    "ConsensusThreshold",
    "FanInStrategy",
    "RegisteredAgent",
    "RoutingPolicy",
    "RoutingStrategy",
    "ScopedToken",
    "SpanRecord",
    "Task",
    "TaskStatus",
    "Workflow",
    "WorkflowResult",
    # Components
    "AgentRegistry",
    "AuthManager",
    "HealthScorer",
    "MeshTracer",
    "RedisAgentRegistry",
    "Router",
    "WorkflowCoordinator",
    # Exceptions
    "AgentAlreadyRegisteredError",
    "AgentNotFoundError",
    "AuthError",
    "ConsensusNotReachedError",
    "CyclicDependencyError",
    "HealthCheckFailedError",
    "InsufficientScopeError",
    "ErrorCode",
    "JsonRpcError",
    "MeshError",
    "NoCapableAgentError",
    "ProtocolError",
    "QueueFullError",
    "RoutingError",
    "TaskExecutionError",
    "TokenExpiredError",
    "WorkflowError",
]
