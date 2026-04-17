# a2a-mesh

[![CI](https://github.com/sushaan-k/a2a-mesh/actions/workflows/ci.yml/badge.svg)](https://github.com/sushaan-k/a2a-mesh/actions)
[![PyPI](https://img.shields.io/pypi/v/a2a-mesh.svg)](https://pypi.org/project/a2a-mesh/)
[![PyPI Downloads](https://img.shields.io/pypi/dm/a2a-mesh.svg)](https://pypi.org/project/a2a-mesh/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Multi-agent mesh runtime — A2A protocol, semantic routing, DAG workflows, and distributed tracing.**

`a2a-mesh` implements Google's [Agent-to-Agent (A2A) protocol](https://google.github.io/A2A/) as a production-grade mesh runtime. Agents register capabilities, discover each other via semantic search, form dynamic DAG workflows, and exchange structured messages with full OpenTelemetry tracing.

---

## The Problem

Multi-agent frameworks (LangGraph, AutoGen, CrewAI) are orchestration frameworks — one coordinator, static topology, manually wired message passing. Real production systems need *dynamic* agent discovery (route to whichever agent can handle this), *fault tolerance* (reroute when an agent fails), and *observability* (trace every hop). The A2A protocol defines this standard, but nobody has built the mesh runtime.

## Solution

```python
from a2a_mesh import Mesh, Agent, Task

mesh = Mesh()

@mesh.agent(capabilities=["sql_query", "data_analysis"])
class AnalystAgent(Agent):
    async def handle(self, task: Task) -> str:
        # run SQL, return structured results
        ...

@mesh.agent(capabilities=["report_writing", "formatting"])
class WriterAgent(Agent):
    async def handle(self, task: Task) -> str:
        # format results into a report
        ...

await mesh.start()

# Semantic routing — mesh finds the right agent automatically
result = await mesh.submit(
    "Analyze Q1 revenue by region and write a board summary",
    trace=True,
)

print(result.output)
print(result.trace.to_jaeger())   # full distributed trace
```

## At a Glance

- **A2A protocol** — full spec implementation: agent cards, task lifecycle, streaming, push notifications
- **Semantic routing** — embedding-based capability matching, not manual wiring
- **DAG workflows** — automatic dependency resolution for multi-step tasks
- **Fault tolerance** — health checks, retry with exponential backoff, capability-based failover
- **OpenTelemetry** — every agent hop is a trace span, exportable to Jaeger, Honeycomb, etc.

## Install

```bash
pip install a2a-mesh
```

## Protocol Support

| A2A Feature | Status |
|---|---|
| Agent Card (discovery) | ✅ |
| Task lifecycle (submitted → working → completed) | ✅ |
| Streaming responses | ✅ |
| Push notifications | ✅ |
| Multi-turn tasks | ✅ |
| Semantic routing extension | ✅ |

## Architecture

```
Mesh
 ├── Registry           # agent discovery via embedding similarity
 ├── Router             # semantic capability → agent mapping
 ├── WorkflowEngine     # DAG dependency resolution and execution
 ├── A2AProtocol        # message serialization / task state machine
 └── Tracer             # OpenTelemetry span emission per hop
```

## Contributing

PRs welcome. Run `pip install -e ".[dev]"` then `pytest`. Star the repo if you find it useful ⭐
