# a2a-mesh

## Lightweight Multi-Agent Coordination Runtime

### The Problem

The agent protocol stack is now standardized:
- **MCP** (Model Context Protocol) — how agents access tools and data
- **A2A** (Agent-to-Agent Protocol) — how agents communicate with each other

But here's the gap: these are **protocols**, not **runtimes**. It's like having HTTP defined but no web server. If you want to run multiple agents that discover each other, coordinate tasks, handle failures, and load-balance — you're writing all that infrastructure from scratch.

Enterprise teams building multi-agent systems are reinventing the wheel: service discovery, health checks, message routing, auth delegation, fault tolerance. There's no lightweight open-source runtime that handles the orchestration layer.

### The Solution

`a2a-mesh` is a minimal runtime for multi-agent systems. Think of it as "Kubernetes for agents" — but actually small and usable. It handles:
- **Discovery**: Agents register capabilities; other agents find them
- **Routing**: Task requests get routed to the right agent(s)
- **Coordination**: Multi-agent workflows with dependency management
- **Fault tolerance**: Health checks, failover, retry
- **Observability**: Distributed tracing across agent interactions

### Architecture

```
┌─────────────────────────────────────────────────────┐
│                     a2a-mesh                         │
│                                                      │
│  ┌────────────┐  ┌────────────┐  ┌───────────────┐  │
│  │  Registry   │  │  Router    │  │  Coordinator  │  │
│  │            │  │            │  │               │  │
│  │  - Agent   │  │  - Cap-    │  │  - Workflow   │  │
│  │    cards   │  │    ability │  │    DAGs       │  │
│  │  - Health  │  │    match   │  │  - Dep        │  │
│  │    checks  │  │  - Load    │  │    tracking   │  │
│  │  - Version │  │    balance │  │  - Fan-out    │  │
│  │    mgmt    │  │  - A2A     │  │    fan-in     │  │
│  │            │  │    routing │  │  - Consensus  │  │
│  └────────────┘  └────────────┘  └───────────────┘  │
│                                                      │
│  ┌────────────┐  ┌────────────┐  ┌───────────────┐  │
│  │  Auth       │  │  Tracer    │  │  Gateway      │  │
│  │            │  │            │  │               │  │
│  │  - Token   │  │  - OpenTel │  │  - HTTP/WS    │  │
│  │    exchange│  │    spans   │  │    ingress     │  │
│  │  - Scope   │  │  - Agent   │  │  - Rate limit │  │
│  │    mgmt    │  │    traces  │  │  - Auth        │  │
│  │  - Audit   │  │  - Cost    │  │    middleware  │  │
│  │    log     │  │    tracking│  │               │  │
│  └────────────┘  └────────────┘  └───────────────┘  │
└───────────────────┬─────────────────┬───────────────┘
                    │                 │
        ┌───────────┘                 └───────────┐
        ▼                                         ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Agent A    │  │   Agent B    │  │   Agent C    │
│  (Research)  │  │  (Analysis)  │  │  (Writing)   │
│              │  │              │  │              │
│  MCP tools:  │  │  MCP tools:  │  │  MCP tools:  │
│  web_search  │  │  python_exec │  │  file_write  │
│  fetch_url   │  │  database    │  │  email_send  │
└──────────────┘  └──────────────┘  └──────────────┘
```

### Core Components

#### 1. Agent Registry
Agents register with **Agent Cards** (from the A2A spec) — JSON descriptions of their capabilities, supported input/output formats, and authentication requirements.

```python
from a2a_mesh import AgentCard

card = AgentCard(
    name="research-agent",
    description="Searches the web and synthesizes information",
    capabilities=["web_search", "summarization", "fact_checking"],
    input_formats=["text/plain", "application/json"],
    output_formats=["text/markdown", "application/json"],
    max_concurrent=5,
    cost_per_task=0.02,  # estimated $ per task
    health_endpoint="/health",
)
```

The registry supports:
- **Capability-based discovery**: "Find me an agent that can analyze financial data"
- **Health monitoring**: Periodic health checks, automatic deregistration of dead agents
- **Version management**: Multiple versions of the same agent, gradual rollout

#### 2. Smart Router
Routes task requests to the best available agent based on:
- **Capability match**: Does the agent support this task type?
- **Load**: How many tasks is this agent currently handling?
- **Cost**: Which agent is cheapest for this task?
- **Latency**: Which agent responds fastest?
- **Custom policies**: User-defined routing rules

```python
from a2a_mesh import Router, RoutingPolicy

router = Router(
    policy=RoutingPolicy(
        strategy="least_cost",          # or "least_latency", "round_robin", "custom"
        fallback="any_capable",         # if preferred agent unavailable
        max_queue_depth=10,             # max pending tasks per agent
    )
)
```

#### 3. Workflow Coordinator
Orchestrates multi-agent workflows defined as DAGs (directed acyclic graphs):

```python
from a2a_mesh import Workflow, Task

workflow = Workflow(
    tasks=[
        Task("research", agent="research-agent", input=user_query),
        Task("analyze", agent="analysis-agent", depends_on=["research"]),
        Task("draft", agent="writing-agent", depends_on=["analyze"]),
        Task("review", agent="review-agent", depends_on=["draft"]),
    ],
    fan_out={
        "research": 3,  # Send to 3 research agents in parallel
    },
    fan_in={
        "research": "merge",  # Merge results from parallel research
    },
    consensus={
        "review": {"agents": 2, "threshold": "all_agree"},  # 2 reviewers must agree
    },
)

result = await coordinator.execute(workflow)
```

#### 4. Auth Manager
Handles the gnarly problem of agent-to-agent authentication:
- **Token exchange**: Agent A delegates scoped permissions to Agent B
- **Scope management**: Agent B can only access what Agent A authorized
- **Audit trail**: Every token exchange is logged

#### 5. Distributed Tracer
OpenTelemetry-based tracing across agent interactions:
- Every agent call is a span
- Traces propagate across agent boundaries
- Cost tracking per span (token usage, API costs)

### Technical Stack

- **Language**: Python 3.11+ (with async throughout)
- **Transport**: `httpx` (HTTP) + `websockets` (streaming)
- **Protocol**: A2A (Google's Agent-to-Agent Protocol) over JSON-RPC
- **Tools**: MCP for agent-tool communication
- **Tracing**: OpenTelemetry
- **Registry storage**: In-memory (default) or Redis (production)
- **Auth**: JWT tokens with scoped claims

### API Surface (Draft)

```python
from a2a_mesh import Mesh

# Start a mesh
mesh = Mesh(port=8080)

# Register agents
mesh.register(research_agent)
mesh.register(analysis_agent)
mesh.register(writing_agent)

# Simple task dispatch
result = await mesh.dispatch(
    task="Research the latest developments in quantum computing",
    required_capabilities=["web_search", "summarization"],
)

# Complex workflow
result = await mesh.execute_workflow(workflow)

# Observability
mesh.traces()      # OpenTelemetry trace viewer
mesh.dashboard()   # Web UI showing agent status, load, costs
```

### CLI

```bash
# Start a mesh node
$ a2a-mesh start --port 8080

# Register an agent
$ a2a-mesh register --card agent_card.json --endpoint http://localhost:9001

# List registered agents
$ a2a-mesh agents

# Dispatch a task
$ a2a-mesh dispatch "Analyze Q4 earnings for AAPL" --capabilities financial_analysis

# View traces
$ a2a-mesh traces --last 10

# Dashboard
$ a2a-mesh dashboard  # Opens web UI
```

### What Makes This Novel

1. **First open-source A2A runtime** — the protocol exists, the runtime doesn't
2. **Workflow DAGs with fan-out/fan-in/consensus** — real multi-agent coordination patterns
3. **Cost-aware routing** — nobody else considers token costs in routing decisions
4. **Integrated auth delegation** — the hardest unsolved problem in multi-agent systems
5. **OpenTelemetry tracing** — production observability out of the box

### Repo Structure

```
a2a-mesh/
├── README.md
├── pyproject.toml
├── src/
│   └── a2a_mesh/
│       ├── __init__.py
│       ├── mesh.py             # Main mesh runtime
│       ├── registry.py         # Agent registration + discovery
│       ├── router.py           # Task routing
│       ├── coordinator.py      # Workflow orchestration
│       ├── auth.py             # Token exchange + scope management
│       ├── tracer.py           # OpenTelemetry integration
│       ├── gateway.py          # HTTP/WS gateway
│       ├── protocol/
│       │   ├── a2a.py          # A2A protocol implementation
│       │   └── mcp.py          # MCP bridge
│       ├── dashboard/
│       │   └── app.py          # Web UI
│       └── cli.py
├── tests/
├── examples/
│   ├── research_workflow.py
│   ├── code_review_pipeline.py
│   └── customer_support.py
└── docs/
    ├── architecture.md
    ├── a2a_protocol.md
    └── deployment.md
```

### Research References

- Google A2A Protocol Specification (github.com/google/A2A)
- Anthropic MCP Specification (modelcontextprotocol.io)
- "AI Agent Protocol Ecosystem Map 2026" (Digital Applied)
- Linux Foundation Agentic AI Foundation (Dec 2025 launch)
- "Multi-Agent Systems: A Survey of Coordination Protocols" (AAMAS 2025)
