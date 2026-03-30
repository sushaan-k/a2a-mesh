"""Tests for the CLI interface."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import httpx
import pytest
import respx
from click.testing import CliRunner

from a2a_mesh.cli import cli


class TestCli:
    """Tests for CLI commands."""

    def test_cli_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "a2a-mesh" in result.output

    def test_start_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["start", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--host" in result.output

    def test_register_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["register", "--help"])
        assert result.exit_code == 0
        assert "--card" in result.output

    def test_agents_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["agents", "--help"])
        assert result.exit_code == 0
        assert "--mesh-url" in result.output

    def test_dispatch_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["dispatch", "--help"])
        assert result.exit_code == 0
        assert "--capabilities" in result.output

    def test_traces_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["traces", "--help"])
        assert result.exit_code == 0
        assert "--last" in result.output

    def test_dashboard_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["dashboard", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--host" in result.output

    def test_register_missing_card(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["register", "--card", "/nonexistent/path.json"])
        # click should report an error because the file does not exist
        assert result.exit_code != 0

    def test_log_level_option(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--log-level", "DEBUG", "--help"])
        assert result.exit_code == 0

    def test_start_uses_host_binding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str] = {}

        def fake_serve(self: object, *, host: str) -> None:
            captured["host"] = host

        monkeypatch.setattr("a2a_mesh.mesh.Mesh.serve", fake_serve)

        runner = CliRunner()
        result = runner.invoke(cli, ["start", "--host", "0.0.0.0", "--port", "9090"])
        assert result.exit_code == 0
        assert captured["host"] == "0.0.0.0"

    def test_dashboard_uses_host_binding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str] = {}

        def fake_dashboard(self: object, *, host: str) -> None:
            captured["host"] = host

        monkeypatch.setattr("a2a_mesh.mesh.Mesh.dashboard", fake_dashboard)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["dashboard", "--host", "0.0.0.0", "--port", "8082"],
        )
        assert result.exit_code == 0
        assert captured["host"] == "0.0.0.0"


class TestCliRegisterCommand:
    """Tests for the register command with actual card files."""

    @respx.mock
    def test_register_with_valid_card(self) -> None:
        """Register command reads a card JSON and posts to the mesh."""
        card_data = {
            "name": "cli-agent",
            "capabilities": ["testing"],
        }
        respx.post("http://localhost:8080/agents/register").mock(
            return_value=httpx.Response(
                201, json={"name": "cli-agent", "status": "registered"}
            )
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(card_data, f)
            card_path = f.name

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["register", "--card", card_path, "--endpoint", "http://a:1234"],
        )
        assert result.exit_code == 0
        assert "cli-agent" in result.output

        Path(card_path).unlink()

    def test_register_with_invalid_json_card(self) -> None:
        """Register command fails gracefully with invalid JSON card file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            card_path = f.name

        runner = CliRunner()
        result = runner.invoke(cli, ["register", "--card", card_path])
        assert result.exit_code != 0

        Path(card_path).unlink()

    @respx.mock
    def test_register_server_failure(self) -> None:
        """Register command reports error when server returns non-201."""
        card_data = {"name": "fail-agent", "capabilities": []}
        respx.post("http://localhost:8080/agents/register").mock(
            return_value=httpx.Response(500, text="Server Error")
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(card_data, f)
            card_path = f.name

        runner = CliRunner()
        result = runner.invoke(cli, ["register", "--card", card_path])
        assert result.exit_code != 0

        Path(card_path).unlink()


class TestCliAgentsCommand:
    """Tests for the agents list command."""

    @respx.mock
    def test_agents_list_success(self) -> None:
        """agents command lists agents from the mesh."""
        respx.get("http://localhost:8080/agents").mock(
            return_value=httpx.Response(
                200,
                json={
                    "agents": [
                        {
                            "name": "agent-1",
                            "status": "healthy",
                            "capabilities": ["search"],
                            "current_load": 2,
                        }
                    ]
                },
            )
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["agents"])
        assert result.exit_code == 0
        assert "agent-1" in result.output
        assert "healthy" in result.output

    @respx.mock
    def test_agents_empty(self) -> None:
        """agents command handles empty agent list."""
        respx.get("http://localhost:8080/agents").mock(
            return_value=httpx.Response(200, json={"agents": []})
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["agents"])
        assert result.exit_code == 0
        assert "No agents registered" in result.output

    @respx.mock
    def test_agents_server_error(self) -> None:
        """agents command handles error response."""
        respx.get("http://localhost:8080/agents").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["agents"])
        assert result.exit_code == 0  # click doesn't sys.exit here
        assert "Error" in result.output


class TestCliDispatchCommand:
    """Tests for the dispatch command."""

    @respx.mock
    def test_dispatch_success(self) -> None:
        """dispatch command sends JSON-RPC and displays result."""
        respx.post("http://localhost:8080/rpc").mock(
            return_value=httpx.Response(
                200,
                json={
                    "result": {
                        "status": "completed",
                        "output": "analysis done",
                    }
                },
            )
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["dispatch", "analyze this", "-c", "analysis"])
        assert result.exit_code == 0
        assert "completed" in result.output

    @respx.mock
    def test_dispatch_server_error(self) -> None:
        """dispatch command handles server error."""
        respx.post("http://localhost:8080/rpc").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["dispatch", "do something"])
        assert result.exit_code != 0


class TestCliTracesCommand:
    """Tests for the traces command."""

    @respx.mock
    def test_traces_success(self) -> None:
        """traces command displays spans and total cost."""
        respx.get("http://localhost:8080/traces").mock(
            return_value=httpx.Response(
                200,
                json={
                    "total_cost": 0.05,
                    "spans": [
                        {
                            "operation": "dispatch",
                            "agent_name": "test-agent",
                            "duration_ms": 123.4,
                            "cost": 0.05,
                        }
                    ],
                },
            )
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["traces", "--last", "5"])
        assert result.exit_code == 0
        assert "0.0500" in result.output
        assert "dispatch" in result.output

    @respx.mock
    def test_traces_server_error(self) -> None:
        """traces command handles error response."""
        respx.get("http://localhost:8080/traces").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["traces"])
        assert result.exit_code == 0
        assert "Error" in result.output
