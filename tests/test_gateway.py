"""Tests for the HTTP gateway."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from a2a_mesh.auth import AuthManager
from a2a_mesh.gateway import RateLimiter, create_gateway
from a2a_mesh.mesh import Mesh
from a2a_mesh.models import AgentCard, TaskStatus


@pytest.fixture
def mesh() -> Mesh:
    """Create a Mesh instance for testing."""
    m = Mesh(port=9999, log_level="WARNING")
    m.register(
        AgentCard(
            name="test-agent",
            description="A test agent",
            capabilities=["testing"],
        )
    )
    return m


@pytest.fixture
def client(mesh: Mesh) -> TestClient:
    """Create a Starlette test client."""
    app = create_gateway(mesh)
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["agents"] == 1


class TestAgentsEndpoints:
    """Tests for agent-related endpoints."""

    def test_list_agents(self, client: TestClient) -> None:
        resp = client.get("/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["name"] == "test-agent"
        assert data["agents"][0]["auth_required"] is False

    def test_register_agent(self, client: TestClient) -> None:
        resp = client.post(
            "/agents/register",
            json={
                "name": "new-agent",
                "description": "Freshly registered",
                "capabilities": ["analysis"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "new-agent"
        assert data["status"] == "registered"
        assert data["auth_required"] is False

    def test_register_duplicate_agent(self, client: TestClient) -> None:
        resp = client.post(
            "/agents/register",
            json={
                "name": "test-agent",
                "capabilities": ["testing"],
            },
        )
        assert resp.status_code == 409

    def test_register_invalid_body(self, client: TestClient) -> None:
        resp = client.post(
            "/agents/register",
            content=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400


class TestJsonRpcEndpoint:
    """Tests for the /rpc JSON-RPC endpoint."""

    def test_agents_list_method(self, client: TestClient) -> None:
        resp = client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "agents/list",
                "params": {},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert len(data["result"]["agents"]) >= 1
        assert data["result"]["agents"][0]["auth_required"] is False

    def test_agents_register_method(self, client: TestClient) -> None:
        resp = client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "agents/register",
                "params": {
                    "name": "rpc-agent",
                    "capabilities": ["rpc"],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["name"] == "rpc-agent"
        assert data["result"]["auth_required"] is False

    def test_unknown_method(self, client: TestClient) -> None:
        resp = client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "unknown/method",
                "params": {},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_invalid_json(self, client: TestClient) -> None:
        resp = client.post(
            "/rpc",
            content=b"{broken json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_tasks_send_method(self, client: TestClient, mesh: Mesh) -> None:
        # The agent has no URL, so dispatch returns echo response
        resp = client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tasks/send",
                "params": {
                    "input": "test task",
                    "capabilities": ["testing"],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["status"] == TaskStatus.COMPLETED
        assert data["result"]["task_id"]

    def test_tasks_get_and_cancel_methods(self, client: TestClient) -> None:
        send_resp = client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tasks/send",
                "params": {
                    "input": "inspect me",
                    "capabilities": ["testing"],
                },
            },
        )
        task_id = send_resp.json()["result"]["task_id"]

        get_resp = client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tasks/get",
                "params": {"id": task_id},
            },
        )
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["result"]["task_id"] == task_id
        assert get_data["result"]["status"] == TaskStatus.COMPLETED

        cancel_resp = client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tasks/cancel",
                "params": {"id": task_id},
            },
        )
        assert cancel_resp.status_code == 200
        cancel_data = cancel_resp.json()
        assert cancel_data["result"]["task_id"] == task_id
        assert cancel_data["result"]["status"] in {
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
        }

    def test_malformed_jsonrpc_missing_method(self, client: TestClient) -> None:
        """JSON-RPC request with no method field dispatches to empty method."""
        resp = client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "id": 10, "params": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Empty method is treated as unknown -> error
        assert "error" in data

    def test_malformed_jsonrpc_missing_params(self, client: TestClient) -> None:
        """JSON-RPC request with no params field still works (defaults to {})."""
        resp = client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "id": 11, "method": "agents/list"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data

    def test_malformed_jsonrpc_missing_id(self, client: TestClient) -> None:
        """JSON-RPC request with no id field."""
        resp = client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "agents/list", "params": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] is None
        assert "result" in data

    def test_tasks_send_no_capable_agent(self, client: TestClient) -> None:
        """tasks/send with capabilities no agent has returns error."""
        resp = client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 20,
                "method": "tasks/send",
                "params": {
                    "input": "do something",
                    "capabilities": ["nonexistent_capability"],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_agents_register_via_rpc_duplicate(self, client: TestClient) -> None:
        """Registering a duplicate agent via JSON-RPC returns error."""
        resp = client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 21,
                "method": "agents/register",
                "params": {
                    "name": "test-agent",
                    "capabilities": ["testing"],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_rpc_rate_limiting(self) -> None:
        """Rate limiter integrated into the RPC endpoint blocks excess requests."""
        m = Mesh(port=9998, log_level="WARNING")
        m.register(AgentCard(name="a", capabilities=["x"]))
        app = create_gateway(m)
        c = TestClient(app)

        # The default rate limiter allows 100 requests per 60s.
        # We make 101 requests to trigger the limiter.
        for _ in range(100):
            c.post(
                "/rpc",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "agents/list",
                    "params": {},
                },
            )
        resp = c.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "agents/list",
                "params": {},
            },
        )
        assert resp.status_code == 429
        data = resp.json()
        assert data["error"]["message"] == "Rate limit exceeded"

    def test_empty_json_body(self, client: TestClient) -> None:
        """Sending an empty JSON object should still work (with defaults)."""
        resp = client.post("/rpc", json={})
        assert resp.status_code == 200
        data = resp.json()
        # method defaults to "" which is unknown
        assert "error" in data


class TestTracesEndpoint:
    """Tests for the /traces endpoint."""

    def test_traces_empty(self, client: TestClient) -> None:
        resp = client.get("/traces")
        assert resp.status_code == 200
        data = resp.json()
        assert "spans" in data
        assert "total_cost" in data

    def test_traces_with_limit_param(self, client: TestClient) -> None:
        """The limit query param is accepted."""
        resp = client.get("/traces?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert "spans" in data


class TestGatewayAuth:
    """Tests for auth wiring in the gateway."""

    def test_auth_required_when_manager_is_configured(self) -> None:
        mesh = Mesh(port=9997, log_level="WARNING")
        mesh.register(
            AgentCard(name="auth-agent", capabilities=["testing"], auth_required=True)
        )
        auth_manager = AuthManager(secret="test-secret-key-for-testing-abcde")
        app = create_gateway(mesh, auth_manager=auth_manager)
        client = TestClient(app)

        protected = client.get("/agents")
        assert protected.status_code == 401

        token = auth_manager.issue_token(
            issuer="client",
            subject="mesh",
            scopes=["agents:list"],
        )
        allowed = client.get(
            "/agents",
            headers={"Authorization": f"Bearer {token.token}"},
        )
        assert allowed.status_code == 200

    def test_websocket_rpc_requires_auth_and_supports_jsonrpc(self) -> None:
        mesh = Mesh(port=9996, log_level="WARNING")
        mesh.register(AgentCard(name="ws-agent", capabilities=["testing"]))
        auth_manager = AuthManager(secret="test-secret-key-for-testing-abcde")
        app = create_gateway(mesh, auth_manager=auth_manager)
        client = TestClient(app)

        token = auth_manager.issue_token(
            issuer="client",
            subject="mesh",
            scopes=["agents:list"],
        )
        with client.websocket_connect(
            "/ws",
            headers={"Authorization": f"Bearer {token.token}"},
        ) as websocket:
            websocket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "agents/list",
                    "params": {},
                }
            )
            data = websocket.receive_json()
            assert "result" in data
            assert data["result"]["agents"][0]["name"] == "ws-agent"


class TestRateLimiter:
    """Tests for the rate limiter."""

    def test_allows_under_limit(self) -> None:
        limiter = RateLimiter(max_requests=5, window_seconds=60.0)
        for _ in range(5):
            assert limiter.allow("client1") is True

    def test_blocks_over_limit(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=60.0)
        assert limiter.allow("client1") is True
        assert limiter.allow("client1") is True
        assert limiter.allow("client1") is False

    def test_separate_keys(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=60.0)
        assert limiter.allow("client1") is True
        assert limiter.allow("client2") is True
        assert limiter.allow("client1") is False

    def test_default_configuration(self) -> None:
        """Default limiter allows 100 requests per 60s window."""
        limiter = RateLimiter()
        assert limiter.max_requests == 100
        assert limiter.window_seconds == 60.0
