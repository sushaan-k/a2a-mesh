"""Example: Code Review Pipeline with Consensus.

Demonstrates multi-agent consensus for code review. Two independent
reviewers must agree before a review is accepted, and the pipeline
includes an automated fix-suggestions step.

Usage::

    python examples/code_review_pipeline.py
"""

from __future__ import annotations

import asyncio

from a2a_mesh import (
    AgentCard,
    ConsensusConfig,
    ConsensusThreshold,
    Mesh,
    RoutingPolicy,
    RoutingStrategy,
    Task,
    Workflow,
)


async def main() -> None:
    """Run a code review pipeline with consensus."""

    mesh = Mesh(
        port=8080,
        policy=RoutingPolicy(strategy=RoutingStrategy.LEAST_LATENCY),
        log_level="INFO",
    )

    # Register specialized code review agents
    mesh.register(
        AgentCard(
            name="linter-agent",
            description="Runs static analysis and linting",
            capabilities=["code_analysis", "linting"],
            max_concurrent=10,
            cost_per_task=0.005,
        )
    )

    mesh.register(
        AgentCard(
            name="reviewer-alpha",
            description="Senior code reviewer (style + correctness)",
            capabilities=["code_review", "style_check"],
            max_concurrent=3,
            cost_per_task=0.04,
        )
    )

    mesh.register(
        AgentCard(
            name="reviewer-beta",
            description="Security-focused code reviewer",
            capabilities=["code_review", "security_audit"],
            max_concurrent=3,
            cost_per_task=0.04,
        )
    )

    mesh.register(
        AgentCard(
            name="fixer-agent",
            description="Suggests and applies code fixes",
            capabilities=["code_fix", "refactoring"],
            max_concurrent=5,
            cost_per_task=0.03,
        )
    )

    code_diff = """
    def calculate_total(items):
        total = 0
        for i in range(len(items)):
            total = total + items[i]['price'] * items[i]['qty']
        return total
    """

    # Define the code review workflow
    workflow = Workflow(
        name="code-review-pipeline",
        tasks=[
            Task(
                name="lint",
                agent="linter-agent",
                input=f"Run static analysis on this code:\n{code_diff}",
            ),
            Task(
                name="review",
                required_capabilities=["code_review"],
                input=f"Review this code for quality and correctness:\n{code_diff}",
                depends_on=["lint"],
            ),
            Task(
                name="fix",
                agent="fixer-agent",
                depends_on=["review"],
            ),
        ],
        # Two reviewers must agree on the review
        consensus={
            "review": ConsensusConfig(
                agents=2,
                threshold=ConsensusThreshold.ALL_AGREE,
            )
        },
    )

    print("Starting code review pipeline...")
    result = await mesh.execute_workflow(workflow)

    print(f"\nPipeline completed: {result.status.value}")
    print(f"Total cost: ${result.total_cost:.4f}")

    for task_name, task_result in result.task_results.items():
        print(f"\n--- {task_name} ---")
        print(f"  {task_result}")

    # Auth example: issue a scoped token for the fixer agent
    token = mesh.auth.issue_token(
        issuer="reviewer-alpha",
        subject="fixer-agent",
        scopes=["code_fix:read", "code_fix:write"],
    )
    print(f"\nIssued scoped token for fixer-agent: {token.token[:40]}...")

    # Validate the token
    claims = mesh.auth.validate_token(
        token.token, required_scopes=["code_fix:read"]
    )
    print(f"Token validated. Issuer: {claims['iss']}, Scopes: {claims['scopes']}")

    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
