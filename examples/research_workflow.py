"""Example: Research Workflow Pipeline.

Demonstrates a multi-agent research workflow using a2a-mesh.
Three agents collaborate in a pipeline: research -> analyze -> write.

Usage::

    python examples/research_workflow.py
"""

from __future__ import annotations

import asyncio

from a2a_mesh import (
    AgentCard,
    FanInStrategy,
    Mesh,
    RoutingPolicy,
    RoutingStrategy,
    Task,
    Workflow,
)


async def main() -> None:
    """Run a research workflow across multiple agents."""

    # Initialize the mesh with cost-aware routing
    mesh = Mesh(
        port=8080,
        policy=RoutingPolicy(strategy=RoutingStrategy.LEAST_COST),
        log_level="INFO",
    )

    # Register agents with their capability cards
    mesh.register(
        AgentCard(
            name="research-agent",
            description="Searches the web and synthesizes information",
            capabilities=["web_search", "summarization", "fact_checking"],
            max_concurrent=5,
            cost_per_task=0.02,
        )
    )

    mesh.register(
        AgentCard(
            name="analysis-agent",
            description="Analyzes data and generates insights",
            capabilities=["data_analysis", "financial_analysis", "summarization"],
            max_concurrent=3,
            cost_per_task=0.05,
        )
    )

    mesh.register(
        AgentCard(
            name="writing-agent",
            description="Writes reports and articles",
            capabilities=["writing", "formatting", "summarization"],
            max_concurrent=10,
            cost_per_task=0.01,
        )
    )

    # Define a research workflow DAG
    workflow = Workflow(
        name="quantum-computing-research",
        tasks=[
            Task(
                name="research",
                agent="research-agent",
                input="Find the latest developments in quantum computing "
                "from the past month, focusing on error correction "
                "and practical applications.",
            ),
            Task(
                name="analyze",
                agent="analysis-agent",
                depends_on=["research"],
            ),
            Task(
                name="write",
                agent="writing-agent",
                depends_on=["analyze"],
            ),
        ],
        # Fan out the research phase across 3 parallel researchers
        fan_out={"research": 3},
        fan_in={"research": FanInStrategy.MERGE},
    )

    # Execute the workflow
    print("Starting research workflow...")
    result = await mesh.execute_workflow(workflow)

    print(f"\nWorkflow completed with status: {result.status.value}")
    print(f"Total cost: ${result.total_cost:.4f}")

    for task_name, task_result in result.task_results.items():
        print(f"\n--- {task_name} ---")
        print(f"  Result: {task_result}")

    if result.errors:
        print("\nErrors:")
        for task_name, error in result.errors.items():
            print(f"  {task_name}: {error}")

    # Show traces
    print("\n--- Traces ---")
    for span in mesh.traces(limit=10):
        print(
            f"  [{span.operation}] agent={span.agent_name} "
            f"duration={span.duration_ms:.1f}ms cost=${span.cost:.4f}"
        )

    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
