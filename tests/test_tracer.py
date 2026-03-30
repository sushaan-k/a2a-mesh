"""Tests for the distributed tracer."""

from __future__ import annotations

import pytest

from a2a_mesh.tracer import MeshTracer


class TestMeshTracer:
    """Tests for MeshTracer."""

    @pytest.mark.asyncio
    async def test_trace_task_creates_span(self, tracer: MeshTracer) -> None:
        async with tracer.trace_task("test-op", agent_name="agent-a") as span:
            span.cost = 0.01

        assert len(tracer.spans) == 1
        recorded = tracer.spans[0]
        assert recorded.operation == "test-op"
        assert recorded.agent_name == "agent-a"
        assert recorded.cost == 0.01
        assert recorded.status == "ok"
        assert recorded.duration_ms > 0

    @pytest.mark.asyncio
    async def test_trace_task_records_error(self, tracer: MeshTracer) -> None:
        with pytest.raises(ValueError, match="boom"):
            async with tracer.trace_task("fail-op") as _span:
                raise ValueError("boom")

        assert len(tracer.spans) == 1
        assert tracer.spans[0].status == "error"

    @pytest.mark.asyncio
    async def test_trace_ids_populated(self, tracer: MeshTracer) -> None:
        async with tracer.trace_task("op") as _span:
            pass

        recorded = tracer.spans[0]
        assert recorded.trace_id
        assert recorded.span_id
        assert len(recorded.trace_id) == 32  # 128-bit hex
        assert len(recorded.span_id) == 16  # 64-bit hex

    @pytest.mark.asyncio
    async def test_get_traces_returns_recent_first(self, tracer: MeshTracer) -> None:
        async with tracer.trace_task("first"):
            pass
        async with tracer.trace_task("second"):
            pass

        traces = tracer.get_traces(limit=10)
        assert traces[0].operation == "second"
        assert traces[1].operation == "first"

    @pytest.mark.asyncio
    async def test_get_traces_respects_limit(self, tracer: MeshTracer) -> None:
        for i in range(10):
            async with tracer.trace_task(f"op-{i}"):
                pass

        traces = tracer.get_traces(limit=3)
        assert len(traces) == 3

    @pytest.mark.asyncio
    async def test_get_trace_by_id(self, tracer: MeshTracer) -> None:
        async with tracer.trace_task("tracked") as _span:
            pass

        trace_id = tracer.spans[0].trace_id
        matching = tracer.get_trace_by_id(trace_id)
        assert len(matching) == 1
        assert matching[0].operation == "tracked"

    @pytest.mark.asyncio
    async def test_get_trace_by_id_no_match(self, tracer: MeshTracer) -> None:
        matching = tracer.get_trace_by_id("nonexistent-id")
        assert matching == []

    @pytest.mark.asyncio
    async def test_total_cost(self, tracer: MeshTracer) -> None:
        async with tracer.trace_task("op1") as span:
            span.cost = 0.05
        async with tracer.trace_task("op2") as span:
            span.cost = 0.03

        assert abs(tracer.total_cost() - 0.08) < 1e-9

    @pytest.mark.asyncio
    async def test_total_cost_empty(self, tracer: MeshTracer) -> None:
        assert tracer.total_cost() == 0.0

    def test_shutdown(self, tracer: MeshTracer) -> None:
        # Should not raise
        tracer.shutdown()

    @pytest.mark.asyncio
    async def test_custom_attributes(self, tracer: MeshTracer) -> None:
        async with tracer.trace_task("op", attributes={"task_id": "abc123"}) as _span:
            pass

        recorded = tracer.spans[0]
        assert recorded.attributes["task_id"] == "abc123"
