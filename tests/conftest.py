"""Shared fixtures for a2a-mesh tests."""

from __future__ import annotations

import pytest

from a2a_mesh.auth import AuthManager
from a2a_mesh.models import (
    AgentCard,
    RoutingPolicy,
    RoutingStrategy,
    Task,
    Workflow,
)
from a2a_mesh.registry import AgentRegistry
from a2a_mesh.router import Router
from a2a_mesh.tracer import MeshTracer


@pytest.fixture
def research_card() -> AgentCard:
    """Agent card for a research agent."""
    return AgentCard(
        name="research-agent",
        description="Searches the web and synthesizes information",
        capabilities=["web_search", "summarization", "fact_checking"],
        url="http://localhost:9001",
        max_concurrent=5,
        cost_per_task=0.02,
    )


@pytest.fixture
def analysis_card() -> AgentCard:
    """Agent card for an analysis agent."""
    return AgentCard(
        name="analysis-agent",
        description="Analyzes data and generates insights",
        capabilities=["data_analysis", "financial_analysis", "summarization"],
        url="http://localhost:9002",
        max_concurrent=3,
        cost_per_task=0.05,
    )


@pytest.fixture
def writing_card() -> AgentCard:
    """Agent card for a writing agent."""
    return AgentCard(
        name="writing-agent",
        description="Writes content in various formats",
        capabilities=["writing", "formatting", "summarization"],
        url="http://localhost:9003",
        max_concurrent=10,
        cost_per_task=0.01,
    )


@pytest.fixture
def registry() -> AgentRegistry:
    """An empty agent registry."""
    return AgentRegistry(health_interval=600.0)


@pytest.fixture
def populated_registry(
    registry: AgentRegistry,
    research_card: AgentCard,
    analysis_card: AgentCard,
    writing_card: AgentCard,
) -> AgentRegistry:
    """A registry with three agents pre-registered."""
    registry.register(research_card)
    registry.register(analysis_card)
    registry.register(writing_card)
    return registry


@pytest.fixture
def router(populated_registry: AgentRegistry) -> Router:
    """A router backed by the populated registry."""
    return Router(
        populated_registry,
        policy=RoutingPolicy(strategy=RoutingStrategy.LEAST_COST),
    )


@pytest.fixture
def auth_manager() -> AuthManager:
    """An auth manager with a fixed secret."""
    return AuthManager(secret="test-secret-key-for-testing-abcde")


@pytest.fixture
def tracer() -> MeshTracer:
    """A mesh tracer for testing."""
    return MeshTracer(service_name="test-mesh")


@pytest.fixture
def sample_task() -> Task:
    """A sample task for testing."""
    return Task(
        name="test-task",
        input="Analyze the latest market trends",
        required_capabilities=["summarization"],
    )


@pytest.fixture
def sample_workflow() -> Workflow:
    """A sample workflow with dependencies."""
    return Workflow(
        name="test-workflow",
        tasks=[
            Task(name="research", agent="research-agent", input="topic"),
            Task(name="analyze", agent="analysis-agent", depends_on=["research"]),
            Task(name="write", agent="writing-agent", depends_on=["analyze"]),
        ],
    )
