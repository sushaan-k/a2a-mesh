"""Agent health score computation for a2a-mesh.

Tracks response times and error rates per agent and computes a composite
health score between 0.0 (completely unhealthy) and 1.0 (perfect). The
score degrades on failures and recovers gradually over successful requests.
"""

from __future__ import annotations

import math

from a2a_mesh._logging import get_logger
from a2a_mesh.models import RegisteredAgent

logger = get_logger(__name__)

# Defaults for health score computation
_DECAY_FACTOR = 0.15  # How much a single failure degrades the score
_RECOVERY_FACTOR = 0.05  # How much a single success recovers the score
_LATENCY_THRESHOLD_MS = 5000.0  # Latency above this penalises the score


class HealthScorer:
    """Computes and updates composite health scores for agents.

    The score combines error rate and latency into a single 0-1 value.
    Failures cause fast degradation; successes cause slow recovery --
    mirroring real-world trust dynamics.

    Attributes:
        decay_factor: Score penalty per failure (0-1).
        recovery_factor: Score recovery per success (0-1).
        latency_threshold_ms: Latency above which a soft penalty applies.
    """

    def __init__(
        self,
        decay_factor: float = _DECAY_FACTOR,
        recovery_factor: float = _RECOVERY_FACTOR,
        latency_threshold_ms: float = _LATENCY_THRESHOLD_MS,
    ) -> None:
        self.decay_factor = decay_factor
        self.recovery_factor = recovery_factor
        self.latency_threshold_ms = latency_threshold_ms

    def record_success(
        self,
        agent: RegisteredAgent,
        latency_ms: float = 0.0,
    ) -> float:
        """Record a successful request and update the health score.

        Args:
            agent: The agent that completed the request.
            latency_ms: Observed response latency in milliseconds.

        Returns:
            The updated health score.
        """
        agent.total_requests += 1
        # Recover toward 1.0
        agent.health_score = min(
            1.0, agent.health_score + self.recovery_factor * (1.0 - agent.health_score)
        )

        # Apply a soft penalty for high latency (sigmoid curve)
        if latency_ms > self.latency_threshold_ms and self.latency_threshold_ms > 0:
            overshoot = latency_ms / self.latency_threshold_ms
            penalty = 1.0 - 1.0 / (1.0 + math.exp(-2.0 * (overshoot - 2.0)))
            agent.health_score = max(0.0, agent.health_score * penalty)

        logger.debug(
            "health.score_updated",
            agent=agent.card.name,
            score=round(agent.health_score, 4),
            outcome="success",
        )
        return agent.health_score

    def record_failure(self, agent: RegisteredAgent) -> float:
        """Record a failed request and degrade the health score.

        Args:
            agent: The agent that failed the request.

        Returns:
            The updated health score.
        """
        agent.total_requests += 1
        agent.total_failures += 1
        agent.health_score = max(0.0, agent.health_score - self.decay_factor)

        logger.debug(
            "health.score_updated",
            agent=agent.card.name,
            score=round(agent.health_score, 4),
            outcome="failure",
        )
        return agent.health_score

    def score(self, agent: RegisteredAgent) -> float:
        """Return the current health score for an agent.

        Args:
            agent: The agent to query.

        Returns:
            Health score between 0.0 and 1.0.
        """
        return agent.health_score
