"""Core data models for a2a-mesh.

All domain objects are Pydantic models with full validation. These models
represent the fundamental concepts of the A2A mesh: agent cards, tasks,
workflows, routing policies, and authentication tokens.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(UTC)


def _new_id() -> str:
    """Generate a new unique identifier."""
    return uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AgentStatus(StrEnum):
    """Health status of a registered agent."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class TaskStatus(StrEnum):
    """Lifecycle status of a task."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RoutingStrategy(StrEnum):
    """Strategy used to select an agent for a task."""

    ROUND_ROBIN = "round_robin"
    LEAST_COST = "least_cost"
    LEAST_LATENCY = "least_latency"
    LEAST_LOAD = "least_load"
    RANDOM = "random"
    HEALTH_SCORE = "health_score"


class FanInStrategy(StrEnum):
    """Strategy for merging results from parallel fan-out tasks."""

    MERGE = "merge"
    FIRST = "first"
    VOTE = "vote"


class ConsensusThreshold(StrEnum):
    """Threshold for consensus among multiple agents."""

    ALL_AGREE = "all_agree"
    MAJORITY = "majority"
    ANY = "any"


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------


class AgentCard(BaseModel):
    """A2A Agent Card describing an agent's capabilities and metadata.

    Agent Cards are the fundamental unit of service discovery in the mesh.
    They advertise what an agent can do, how to reach it, and its operational
    characteristics.

    Attributes:
        name: Unique human-readable agent identifier.
        description: What this agent does.
        url: HTTP endpoint where the agent can be reached.
        capabilities: List of capability tags the agent supports.
        input_formats: MIME types the agent accepts.
        output_formats: MIME types the agent produces.
        version: Semantic version string of the agent.
        max_concurrent: Maximum number of concurrent tasks.
        cost_per_task: Estimated dollar cost per task execution.
        health_endpoint: Relative path to the health check endpoint.
        auth_required: Whether this agent requires authentication.
        metadata: Arbitrary key-value metadata.
    """

    name: str
    description: str = ""
    url: str = ""
    capabilities: list[str] = Field(default_factory=list)
    input_formats: list[str] = Field(
        default_factory=lambda: ["text/plain", "application/json"]
    )
    output_formats: list[str] = Field(
        default_factory=lambda: ["text/plain", "application/json"]
    )
    version: str = "1.0.0"
    max_concurrent: int = 10
    cost_per_task: float = 0.0
    health_endpoint: str = "/health"
    auth_required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Registered Agent (internal state)
# ---------------------------------------------------------------------------


class RegisteredAgent(BaseModel):
    """Internal representation of an agent registered in the mesh.

    Extends the agent card with runtime state: current load, health status,
    latency measurements, health score, and registration timestamps.

    Attributes:
        agent_id: Unique identifier assigned at registration.
        card: The agent's capability card.
        status: Current health status.
        current_load: Number of in-flight tasks.
        avg_latency_ms: Exponential moving average of response latency.
        health_score: Composite score 0.0-1.0 that degrades on failures.
        total_requests: Lifetime request count for this agent.
        total_failures: Lifetime failure count for this agent.
        registered_at: When the agent was registered.
        last_health_check: Timestamp of the last successful health check.
    """

    agent_id: str = Field(default_factory=_new_id)
    card: AgentCard
    status: AgentStatus = AgentStatus.UNKNOWN
    current_load: int = 0
    avg_latency_ms: float = 0.0
    health_score: float = 1.0
    total_requests: int = 0
    total_failures: int = 0
    registered_at: datetime = Field(default_factory=_utcnow)
    last_health_check: datetime | None = None


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class Task(BaseModel):
    """A unit of work to be executed by an agent.

    Tasks can be standalone dispatches or nodes in a workflow DAG. Each task
    targets a specific agent (by name) or a set of required capabilities.

    Attributes:
        task_id: Unique task identifier.
        name: Human-readable task name (used as DAG node key).
        agent: Target agent name (optional if capabilities are specified).
        input: The task payload / prompt.
        depends_on: List of task names this task depends on.
        required_capabilities: Capabilities needed to handle this task.
        status: Current lifecycle status.
        result: Output produced by the agent.
        error: Error message if the task failed.
        created_at: When the task was created.
        started_at: When execution began.
        completed_at: When execution finished.
        cost: Actual cost of execution.
        metadata: Arbitrary key-value metadata.
    """

    task_id: str = Field(default_factory=_new_id)
    name: str = ""
    agent: str = ""
    input: Any = None
    depends_on: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cost: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Routing Policy
# ---------------------------------------------------------------------------


class RoutingPolicy(BaseModel):
    """Configuration for how tasks are routed to agents.

    Attributes:
        strategy: The routing algorithm to use.
        fallback: Fallback strategy if primary routing fails.
        max_queue_depth: Maximum pending tasks per agent before overflow.
        sticky: If True, repeat tasks go to the same agent.
        timeout_seconds: How long to wait for a route before failing.
    """

    strategy: RoutingStrategy = RoutingStrategy.ROUND_ROBIN
    fallback: str = "any_capable"
    max_queue_depth: int = 100
    sticky: bool = False
    timeout_seconds: float = 30.0


# ---------------------------------------------------------------------------
# Consensus Config
# ---------------------------------------------------------------------------


class ConsensusConfig(BaseModel):
    """Configuration for multi-agent consensus on a task.

    Attributes:
        agents: Number of agents that must evaluate the task.
        threshold: Agreement threshold required.
    """

    agents: int = 2
    threshold: ConsensusThreshold = ConsensusThreshold.ALL_AGREE


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


class Workflow(BaseModel):
    """A directed acyclic graph of tasks forming a multi-agent workflow.

    Workflows define the dependency structure, parallelism (fan-out),
    result aggregation (fan-in), and consensus requirements for complex
    multi-agent pipelines.

    Attributes:
        workflow_id: Unique workflow identifier.
        name: Human-readable workflow name.
        tasks: Ordered list of tasks in the workflow.
        fan_out: Mapping of task name to parallelism count.
        fan_in: Mapping of task name to aggregation strategy.
        consensus: Mapping of task name to consensus configuration.
        metadata: Arbitrary key-value metadata.
    """

    workflow_id: str = Field(default_factory=_new_id)
    name: str = ""
    tasks: list[Task] = Field(default_factory=list)
    fan_out: dict[str, int] = Field(default_factory=dict)
    fan_in: dict[str, FanInStrategy] = Field(default_factory=dict)
    consensus: dict[str, ConsensusConfig] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Workflow Result
# ---------------------------------------------------------------------------


class WorkflowResult(BaseModel):
    """Result of executing a workflow.

    Attributes:
        workflow_id: ID of the workflow that produced this result.
        status: Final status of the workflow.
        task_results: Mapping of task name to its result.
        total_cost: Sum of costs across all tasks.
        started_at: When workflow execution began.
        completed_at: When workflow execution finished.
        errors: Mapping of task name to error message for failed tasks.
    """

    workflow_id: str
    status: TaskStatus = TaskStatus.COMPLETED
    task_results: dict[str, Any] = Field(default_factory=dict)
    total_cost: float = 0.0
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None
    errors: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Auth Models
# ---------------------------------------------------------------------------


class ScopedToken(BaseModel):
    """A scoped JWT token for agent-to-agent authentication.

    Attributes:
        token: The encoded JWT string.
        issuer: Agent that issued the token.
        subject: Agent the token is issued to.
        scopes: List of permitted scopes.
        issued_at: When the token was issued.
        expires_at: When the token expires.
    """

    token: str
    issuer: str
    subject: str
    scopes: list[str] = Field(default_factory=list)
    issued_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None


class AuditEntry(BaseModel):
    """An entry in the authentication audit log.

    Attributes:
        entry_id: Unique audit entry identifier.
        timestamp: When the event occurred.
        issuer: Who initiated the action.
        subject: Who was acted upon.
        action: What happened.
        scopes: Scopes involved.
        success: Whether the action succeeded.
        detail: Additional detail string.
    """

    entry_id: str = Field(default_factory=_new_id)
    timestamp: datetime = Field(default_factory=_utcnow)
    issuer: str = ""
    subject: str = ""
    action: str = ""
    scopes: list[str] = Field(default_factory=list)
    success: bool = True
    detail: str = ""


# ---------------------------------------------------------------------------
# Trace Models
# ---------------------------------------------------------------------------


class SpanRecord(BaseModel):
    """A recorded span from the distributed tracer.

    Attributes:
        trace_id: Distributed trace identifier.
        span_id: Unique span identifier.
        parent_span_id: Parent span for nested calls.
        operation: Name of the operation.
        agent_name: Agent that executed the operation.
        started_at: When the span began.
        ended_at: When the span ended.
        duration_ms: Duration in milliseconds.
        cost: Cost attributed to this span.
        status: Outcome status.
        attributes: Arbitrary span attributes.
    """

    trace_id: str = Field(default_factory=_new_id)
    span_id: str = Field(default_factory=_new_id)
    parent_span_id: str | None = None
    operation: str = ""
    agent_name: str = ""
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None
    duration_ms: float = 0.0
    cost: float = 0.0
    status: str = "ok"
    attributes: dict[str, Any] = Field(default_factory=dict)
