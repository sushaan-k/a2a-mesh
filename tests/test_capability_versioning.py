"""Tests for agent capability versioning."""

from __future__ import annotations

from a2a_mesh.models import AgentCard, Task
from a2a_mesh.registry import AgentRegistry, _capabilities_match, _parse_capability
from a2a_mesh.router import Router


class TestParseCapability:
    """Tests for the _parse_capability helper."""

    def test_unversioned(self) -> None:
        assert _parse_capability("web_search") == ("web_search", None)

    def test_versioned(self) -> None:
        assert _parse_capability("summarization@v2") == ("summarization", "v2")

    def test_version_with_dots(self) -> None:
        assert _parse_capability("analysis@v1.2") == ("analysis", "v1.2")


class TestCapabilitiesMatch:
    """Tests for the _capabilities_match helper."""

    def test_empty_required_matches_anything(self) -> None:
        assert _capabilities_match([], ["web_search", "summarization"])

    def test_exact_match(self) -> None:
        assert _capabilities_match(["web_search"], ["web_search", "summarization"])

    def test_missing_capability(self) -> None:
        assert not _capabilities_match(["quantum"], ["web_search"])

    def test_versioned_required_matches_versioned_advertised(self) -> None:
        assert _capabilities_match(
            ["summarization@v2"], ["summarization@v2", "web_search"]
        )

    def test_versioned_required_rejects_wrong_version(self) -> None:
        assert not _capabilities_match(
            ["summarization@v2"], ["summarization@v1", "web_search"]
        )

    def test_unversioned_required_matches_versioned_advertised(self) -> None:
        """Requesting 'summarization' matches agents with 'summarization@v2'."""
        assert _capabilities_match(["summarization"], ["summarization@v2"])

    def test_unversioned_required_matches_unversioned_advertised(self) -> None:
        assert _capabilities_match(["summarization"], ["summarization"])

    def test_multiple_versions_advertised(self) -> None:
        advertised = ["summarization@v1", "summarization@v2", "web_search"]
        assert _capabilities_match(["summarization@v1"], advertised)
        assert _capabilities_match(["summarization@v2"], advertised)
        assert not _capabilities_match(["summarization@v3"], advertised)


class TestVersionedRouting:
    """Tests for routing with versioned capabilities."""

    def test_route_to_versioned_agent(self) -> None:
        registry = AgentRegistry(health_interval=600.0)
        registry.register(AgentCard(name="agent-v1", capabilities=["summarization@v1"]))
        registry.register(AgentCard(name="agent-v2", capabilities=["summarization@v2"]))

        router = Router(registry)
        task = Task(name="t", required_capabilities=["summarization@v2"])
        selected = router.route(task)
        assert selected.card.name == "agent-v2"

    def test_unversioned_request_matches_both(self) -> None:
        registry = AgentRegistry(health_interval=600.0)
        registry.register(AgentCard(name="agent-v1", capabilities=["summarization@v1"]))
        registry.register(AgentCard(name="agent-v2", capabilities=["summarization@v2"]))

        router = Router(registry)
        task = Task(name="t", required_capabilities=["summarization"])
        selected = router.route_multi(task, count=5)
        names = {a.card.name for a in selected}
        assert names == {"agent-v1", "agent-v2"}

    def test_versioned_capability_in_registry_find(self) -> None:
        registry = AgentRegistry(health_interval=600.0)
        registry.register(
            AgentCard(
                name="multi-cap",
                capabilities=["summarization@v1", "summarization@v2", "web_search"],
            )
        )
        # Exact version match
        agents = registry.find_by_capability(["summarization@v2"], healthy_only=False)
        assert len(agents) == 1
        assert agents[0].card.name == "multi-cap"

        # Wrong version
        agents = registry.find_by_capability(["summarization@v3"], healthy_only=False)
        assert len(agents) == 0
