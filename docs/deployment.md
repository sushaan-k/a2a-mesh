# Deployment Guide

## Local Development

The simplest way to run a2a-mesh is locally for development:

```bash
pip install -e ".[dev]"
a2a-mesh start --host 0.0.0.0 --port 8080
```

This starts the mesh gateway on port 8080 with an in-memory registry. Agents register via HTTP, WebSocket JSON-RPC, or the Python API.

## Production Considerations

### Single-Node Deployment

For moderate workloads, a single mesh node is sufficient:

```bash
pip install a2a-mesh
a2a-mesh start --host 0.0.0.0 --port 8080 --log-level INFO
```

**Recommended settings:**
- Run behind a reverse proxy (nginx, Caddy) for TLS termination.
- Set `--log-level WARNING` in production to reduce log volume.
- Configure health checks from your orchestrator (e.g., Docker healthcheck against `/health`).

### Docker

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["a2a-mesh", "start", "--port", "8080"]
```

```bash
docker build -t a2a-mesh .
docker run -p 8080:8080 a2a-mesh
```

### Docker Compose

```yaml
version: "3.9"
services:
  mesh:
    build: .
    ports:
      - "8080:8080"
      - "8081:8081"
    environment:
      - LOG_LEVEL=INFO

  research-agent:
    image: your-research-agent:latest
    ports:
      - "9001:9001"

  analysis-agent:
    image: your-analysis-agent:latest
    ports:
      - "9002:9002"
```

### Programmatic Startup

For embedding the mesh in a larger application:

```python
from a2a_mesh import Mesh, AgentCard, RoutingPolicy, RoutingStrategy

mesh = Mesh(
    port=8080,
    policy=RoutingPolicy(
        strategy=RoutingStrategy.LEAST_COST,
        max_queue_depth=50,
    ),
    auth_secret="your-production-secret",  # set explicitly in prod
    log_level="WARNING",
    health_interval=15.0,
)

mesh.register(AgentCard(
    name="research",
    url="http://research-agent:9001",
    capabilities=["web_search"],
))

mesh.serve(host="0.0.0.0")  # Blocks, runs uvicorn
```

## Configuration

### Environment Variables

a2a-mesh is configured through constructor arguments. In container deployments, pass values through environment variables in your entrypoint script:

| Parameter | Default | Description |
|---|---|---|
| `port` | 8080 | HTTP gateway port |
| `auth_secret` | Auto-generated | JWT signing secret |
| `log_level` | INFO | Logging verbosity |
| `health_interval` | 30.0 | Seconds between health checks |

### Authentication

In production, always set an explicit `auth_secret`:

```python
mesh = Mesh(auth_secret="your-256-bit-secret-here")
```

The secret signs all JWT tokens for agent-to-agent auth. If not set, a random secret is generated at startup, which means tokens do not survive restarts.

### Rate Limiting

The gateway includes a built-in token-bucket rate limiter. Default: 100 requests per 60-second window per client IP. Adjust by modifying the `RateLimiter` in `gateway.py` or by placing a more sophisticated rate limiter (e.g., nginx) in front.

## Monitoring

### Health Check

```bash
curl http://localhost:8080/health
```

Returns:
```json
{"status": "healthy", "agents": 3}
```

### Traces

```bash
curl http://localhost:8080/traces?limit=20
```

Returns recent OpenTelemetry spans with cost data.

### Dashboard

The built-in web dashboard shows agent status, load, and cost:

```bash
a2a-mesh dashboard --host 0.0.0.0 --port 8081
```

Open `http://localhost:8081` in a browser.

### OpenTelemetry Export

To export traces to an external collector (Jaeger, Zipkin, Datadog):

```python
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

exporter = OTLPSpanExporter(endpoint="http://collector:4317")
mesh = Mesh(port=8080)
# Replace the default tracer
mesh.tracer._provider.add_span_processor(BatchSpanProcessor(exporter))
```

## Scaling

### Current Limitations

- Registry is in-memory (single-node only by default).
- No built-in clustering or leader election.
- Rate limiter state is per-process.

### Scaling Path

For multi-node deployments:

1. **Shared registry**: Use the Redis optional dependency (`pip install a2a-mesh[redis]`) and the built-in `RedisAgentRegistry` for shared discovery state across mesh nodes.
2. **Load balancer**: Place multiple mesh instances behind a load balancer. Each can route to the same pool of agents.
3. **External rate limiting**: Use a dedicated rate limiter (Redis-based or API gateway) instead of the built-in one.
