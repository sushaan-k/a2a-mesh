# Architecture

## Overview

a2a-mesh is a lightweight coordination runtime for multi-agent systems. It sits between client applications and individual agents, providing the infrastructure layer that protocols like A2A and MCP do not cover: service discovery, intelligent routing, workflow orchestration, authentication, and observability.

## System Design

```
                       ┌─────────────────┐
                       │  Client / CLI   │
                       └────────┬────────┘
                                │
                       HTTP / JSON-RPC 2.0
                                │
                       ┌────────▼────────┐
                       │  HTTP Gateway   │
                       │  (Starlette)    │
                       │                 │
                       │  - Rate limit   │
                       │  - Auth check   │
                       │  - JSON-RPC     │
                       └────────┬────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                  │
     ┌────────▼────────┐  ┌────▼─────┐  ┌────────▼────────┐
     │  Agent Registry │  │  Router  │  │   Coordinator   │
     │                 │  │          │  │                  │
     │  - Agent cards  │  │  - Cap   │  │  - Topo sort    │
     │  - Health loop  │  │    match │  │  - Level-based  │
     │  - Capability   │  │  - Load  │  │    concurrency  │
     │    index        │  │    aware │  │  - Fan-out/in   │
     │  - Versions     │  │  - Cost  │  │  - Consensus    │
     │                 │  │    aware │  │                  │
     └────────┬────────┘  └────┬─────┘  └────────┬────────┘
              │                │                  │
              └────────────────┼──────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   A2A Client Pool   │
                    │  (httpx async)      │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
        ┌─────▼─────┐  ┌──────▼──────┐  ┌──────▼──────┐
        │  Agent A  │  │   Agent B   │  │   Agent C   │
        │           │  │             │  │             │
        │  MCP ─►   │  │  MCP ─►    │  │  MCP ─►    │
        │  tools    │  │  tools     │  │  tools     │
        └───────────┘  └─────────────┘  └─────────────┘
```

## Component Details

### Agent Registry

The registry is the service-discovery backbone. It stores Agent Cards (from the A2A spec) and maintains runtime metadata per agent:

- **current_load**: Number of in-flight tasks.
- **avg_latency_ms**: Exponential moving average of response time.
- **status**: Healthy, degraded, unhealthy, or unknown.
- **last_health_check**: Timestamp of the last ping.

A background asyncio task periodically hits each agent's health endpoint and updates status. Unhealthy agents are excluded from routing by default.

Storage is in-memory by default. For shared deployments, use `RedisAgentRegistry` so multiple mesh nodes read and write the same registry state.

### Smart Router

The router evaluates all registered agents against a task's requirements (agent name, required capabilities) and selects the best match according to the active routing policy.

**Strategies:**

| Strategy | Selection Logic |
|---|---|
| `ROUND_ROBIN` | Cycles through capable agents sequentially |
| `LEAST_COST` | Picks agent with lowest `cost_per_task` |
| `LEAST_LATENCY` | Picks agent with lowest `avg_latency_ms` |
| `LEAST_LOAD` | Picks agent with fewest in-flight tasks |
| `RANDOM` | Uniform random selection |

The router also accepts a user-supplied routing hook for custom ranking or selection logic. When provided, the hook can override the built-in strategies for both single-agent and fan-out routing.

The router also supports `route_multi` for fan-out, returning up to N agents sorted by the active strategy.

### Workflow Coordinator

Orchestrates multi-step agent workflows defined as DAGs. The execution model:

1. **Topological sort** validates the DAG (detects cycles).
2. **Level grouping** identifies tasks that can run concurrently (all dependencies met).
3. **Execution** runs each level with `asyncio.gather`.
4. **Dependency injection** passes upstream results to downstream tasks.
5. **Fan-out** replicates a task across multiple agents and merges results (MERGE, FIRST, or VOTE).
6. **Consensus** runs a task on N agents and checks agreement (ALL_AGREE, MAJORITY, or ANY).

The coordinator is decoupled from routing via an executor callback. The Mesh wires it to `_execute_single_task`, which handles routing and A2A dispatch.

### Auth Manager

JWT-based scoped token exchange. Agents issue tokens to delegate specific permissions to other agents:

- **Claims**: issuer, subject, scopes, issued-at, expiry, unique JTI.
- **Validation**: Signature check, expiry check, revocation check, scope check.
- **Audit log**: Append-only log of every token operation.

Tokens are signed with HS256 by default. The secret is auto-generated if not provided, which is fine for single-node deployments.

### Distributed Tracer

Wraps OpenTelemetry to provide mesh-specific tracing:

- Each task dispatch is a span with agent name, duration, and cost attributes.
- Spans are stored in-memory for the `/traces` API.
- An `InMemorySpanExporter` is used by default; swap in any OTel exporter for production.

### HTTP Gateway

Starlette ASGI application exposing:

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Mesh health check |
| `/agents` | GET | List registered agents |
| `/agents/register` | POST | Register an agent |
| `/rpc` | POST | JSON-RPC 2.0 dispatch |
| `/ws` | WS | JSON-RPC 2.0 dispatch over WebSocket |
| `/traces` | GET | Recent span records |

Includes a token-bucket rate limiter keyed by client IP.

### MCP Bridge

Connects to MCP tool servers, discovers available tools, and invokes them on behalf of agents. Uses the MCP JSON-RPC protocol over HTTP.

## Data Flow

1. Client sends a task via HTTP or the Python API.
2. Gateway parses the request and passes it to the Mesh.
3. Mesh creates a Task object and calls the Router.
4. Router queries the Registry for capable agents and selects one.
5. Mesh dispatches the task to the selected agent via A2AClient.
6. Response flows back through the same path.
7. Tracer records spans at each step.

For workflows, the Coordinator manages the DAG execution loop, calling back into the Mesh's executor for each task node.
