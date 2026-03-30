#!/usr/bin/env python3
"""Offline demo for a2a-mesh."""

from __future__ import annotations

import asyncio

from a2a_mesh import AgentCard, Mesh, RoutingPolicy, RoutingStrategy


async def main() -> None:
    mesh = Mesh(
        port=0,
        policy=RoutingPolicy(strategy=RoutingStrategy.LEAST_LOAD),
        log_level="WARNING",
    )
    mesh.register(
        AgentCard(
            name="research-agent",
            capabilities=["research", "summarize"],
            description="Local demo agent",
        )
    )
    mesh.register(
        AgentCard(
            name="ops-agent",
            capabilities=["ops"],
            description="Fallback local demo agent",
        )
    )

    result = await mesh.dispatch(
        "Summarize why event-driven architectures help multi-agent systems.",
        required_capabilities=["summarize"],
    )

    print("a2a-mesh demo")
    print(f"selected agent: {result['agent']}")
    print(f"status: {result['status']}")
    print(f"trace count: {len(mesh.traces())}")


if __name__ == "__main__":
    asyncio.run(main())
