"""Distributed tracing for a2a-mesh.

Provides OpenTelemetry-based tracing across agent interactions. Each agent
call becomes a span, traces propagate across agent boundaries, and cost
tracking is integrated at the span level.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from a2a_mesh._logging import get_logger
from a2a_mesh.models import SpanRecord

logger = get_logger(__name__)


class MeshTracer:
    """Distributed tracer for the a2a-mesh runtime.

    Wraps OpenTelemetry to provide mesh-specific tracing with cost
    tracking and a queryable in-memory span store.

    Attributes:
        service_name: Name of the traced service.
        spans: In-memory list of recorded span records.
    """

    def __init__(
        self,
        service_name: str = "a2a-mesh",
        exporter: SpanExporter | None = None,
    ) -> None:
        """Initialize the tracer.

        Args:
            service_name: OpenTelemetry service name.
            exporter: Custom span exporter. Uses in-memory if not provided.
        """
        self.service_name = service_name
        self.spans: list[SpanRecord] = []
        self._exporter = exporter or InMemorySpanExporter()

        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self._exporter))
        self._provider = provider
        self._tracer = provider.get_tracer(service_name)

    @asynccontextmanager
    async def trace_task(
        self,
        operation: str,
        agent_name: str = "",
        attributes: dict[str, Any] | None = None,
    ) -> AsyncIterator[SpanRecord]:
        """Context manager that creates a traced span for a task.

        Usage::

            async with tracer.trace_task("dispatch", agent_name="research") as span:
                result = await do_work()
                span.cost = 0.05

        Args:
            operation: Name of the operation being traced.
            agent_name: Agent executing the operation.
            attributes: Additional span attributes.

        Yields:
            A SpanRecord that can be mutated during the span's lifetime.
        """
        record = SpanRecord(
            operation=operation,
            agent_name=agent_name,
            started_at=datetime.now(UTC),
            attributes=attributes or {},
        )

        otel_attrs = {
            "mesh.agent": agent_name,
            "mesh.operation": operation,
            **(attributes or {}),
        }

        # Filter to only string/int/float/bool values for OTel
        safe_attrs = {
            k: v
            for k, v in otel_attrs.items()
            if isinstance(v, (str, int, float, bool))
        }

        start_time = time.monotonic()
        with self._tracer.start_as_current_span(
            operation, attributes=safe_attrs
        ) as span:
            otel_ctx = span.get_span_context()
            record.trace_id = format(otel_ctx.trace_id, "032x")
            record.span_id = format(otel_ctx.span_id, "016x")

            try:
                yield record
            except Exception as exc:
                record.status = "error"
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                raise
            finally:
                elapsed_ms = (time.monotonic() - start_time) * 1000
                record.duration_ms = elapsed_ms
                record.ended_at = datetime.now(UTC)
                self.spans.append(record)

                span.set_attribute("mesh.duration_ms", elapsed_ms)
                span.set_attribute("mesh.cost", record.cost)

                logger.debug(
                    "trace.span_ended",
                    operation=operation,
                    agent=agent_name,
                    duration_ms=round(elapsed_ms, 2),
                    cost=record.cost,
                )

    def get_traces(self, limit: int = 50) -> list[SpanRecord]:
        """Return the most recent span records.

        Args:
            limit: Maximum number of spans to return.

        Returns:
            List of span records, most recent first.
        """
        return list(reversed(self.spans[-limit:]))

    def get_trace_by_id(self, trace_id: str) -> list[SpanRecord]:
        """Return all spans belonging to a specific trace.

        Args:
            trace_id: The distributed trace identifier.

        Returns:
            List of spans in the trace, ordered by start time.
        """
        matching = [s for s in self.spans if s.trace_id == trace_id]
        matching.sort(key=lambda s: s.started_at)
        return matching

    def total_cost(self) -> float:
        """Return the total cost across all recorded spans.

        Returns:
            Sum of costs in dollars.
        """
        return sum(s.cost for s in self.spans)

    def shutdown(self) -> None:
        """Shut down the tracer provider."""
        self._provider.shutdown()
        logger.info("tracer.shutdown")
