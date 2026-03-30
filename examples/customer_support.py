"""Example: Customer Support Triage System.

Demonstrates capability-based routing for a customer support system.
Incoming tickets are routed to specialized agents based on the type
of issue, with cost-aware load balancing.

Usage::

    python examples/customer_support.py
"""

from __future__ import annotations

import asyncio

from a2a_mesh import (
    AgentCard,
    Mesh,
    RoutingPolicy,
    RoutingStrategy,
    Task,
)


async def main() -> None:
    """Run a customer support triage system."""

    mesh = Mesh(
        port=8080,
        policy=RoutingPolicy(
            strategy=RoutingStrategy.LEAST_LOAD,
            max_queue_depth=20,
        ),
        log_level="INFO",
    )

    # Register specialized support agents
    mesh.register(
        AgentCard(
            name="billing-agent",
            description="Handles billing inquiries and payment issues",
            capabilities=["billing", "payments", "refunds"],
            max_concurrent=10,
            cost_per_task=0.01,
        )
    )

    mesh.register(
        AgentCard(
            name="technical-agent",
            description="Resolves technical issues and bugs",
            capabilities=["technical_support", "debugging", "api_help"],
            max_concurrent=5,
            cost_per_task=0.03,
        )
    )

    mesh.register(
        AgentCard(
            name="general-agent",
            description="Handles general inquiries",
            capabilities=[
                "general_inquiry",
                "account_management",
                "billing",
            ],
            max_concurrent=15,
            cost_per_task=0.005,
        )
    )

    mesh.register(
        AgentCard(
            name="escalation-agent",
            description="Handles escalated complex cases",
            capabilities=[
                "escalation",
                "billing",
                "technical_support",
                "general_inquiry",
            ],
            max_concurrent=3,
            cost_per_task=0.10,
        )
    )

    # Simulated customer tickets
    tickets = [
        Task(
            name="ticket-001",
            input="I was charged twice for my subscription last month.",
            required_capabilities=["billing"],
        ),
        Task(
            name="ticket-002",
            input="The API returns 500 errors when I send batch requests.",
            required_capabilities=["technical_support", "api_help"],
        ),
        Task(
            name="ticket-003",
            input="How do I update my account email address?",
            required_capabilities=["general_inquiry"],
        ),
        Task(
            name="ticket-004",
            input="I need a refund for order #12345.",
            required_capabilities=["billing", "refunds"],
        ),
        Task(
            name="ticket-005",
            input="My integration stopped working after the last update.",
            required_capabilities=["technical_support", "debugging"],
        ),
    ]

    print("Processing customer support tickets...\n")

    # Dispatch each ticket independently
    results = await asyncio.gather(
        *[mesh.dispatch(ticket) for ticket in tickets],
        return_exceptions=True,
    )

    for ticket, result in zip(tickets, results, strict=True):
        if isinstance(result, Exception):
            print(f"[FAILED] {ticket.name}: {result}")
        else:
            agent = result.get("agent", "unknown")
            print(f"[OK] {ticket.name} -> routed to {agent}")

    # Show system stats
    print("\n--- Agent Load ---")
    for agent in mesh.registry.list_agents():
        print(
            f"  {agent.card.name}: load={agent.current_load} "
            f"status={agent.status.value}"
        )

    print("\n--- Cost Summary ---")
    total = mesh.tracer.total_cost()
    print(f"  Total cost: ${total:.4f}")
    print(f"  Spans recorded: {len(mesh.tracer.spans)}")

    # Show recent traces
    print("\n--- Recent Traces ---")
    for span in mesh.traces(limit=10):
        print(
            f"  [{span.operation}] agent={span.agent_name} "
            f"duration={span.duration_ms:.1f}ms cost=${span.cost:.4f}"
        )

    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
