"""Tests for the authentication manager."""

from __future__ import annotations

import contextlib
from datetime import timedelta

import pytest

from a2a_mesh.auth import AuthManager
from a2a_mesh.exceptions import (
    AuthError,
    InsufficientScopeError,
    TokenExpiredError,
)


class TestTokenIssuance:
    """Tests for token creation."""

    def test_issue_token(self, auth_manager: AuthManager) -> None:
        token = auth_manager.issue_token(
            issuer="agent-a",
            subject="agent-b",
            scopes=["read", "execute"],
        )
        assert token.issuer == "agent-a"
        assert token.subject == "agent-b"
        assert "read" in token.scopes
        assert token.token  # non-empty JWT string

    def test_issue_token_custom_ttl(self, auth_manager: AuthManager) -> None:
        token = auth_manager.issue_token(
            issuer="agent-a",
            subject="agent-b",
            scopes=["read"],
            ttl=timedelta(minutes=5),
        )
        assert token.expires_at is not None
        delta = token.expires_at - token.issued_at
        assert abs(delta.total_seconds() - 300) < 2

    def test_issue_token_adds_audit_entry(self, auth_manager: AuthManager) -> None:
        auth_manager.issue_token(issuer="a", subject="b", scopes=["read"])
        log = auth_manager.get_audit_log()
        assert len(log) == 1
        assert log[0].action == "token_issued"
        assert log[0].success is True


class TestTokenValidation:
    """Tests for token validation."""

    def test_validate_valid_token(self, auth_manager: AuthManager) -> None:
        token = auth_manager.issue_token(
            issuer="agent-a",
            subject="agent-b",
            scopes=["read", "write"],
        )
        claims = auth_manager.validate_token(token.token)
        assert claims["iss"] == "agent-a"
        assert claims["sub"] == "agent-b"
        assert "read" in claims["scopes"]

    def test_validate_with_required_scopes(self, auth_manager: AuthManager) -> None:
        token = auth_manager.issue_token(
            issuer="a", subject="b", scopes=["read", "write"]
        )
        claims = auth_manager.validate_token(token.token, required_scopes=["read"])
        assert claims is not None

    def test_validate_insufficient_scopes_raises(
        self, auth_manager: AuthManager
    ) -> None:
        token = auth_manager.issue_token(issuer="a", subject="b", scopes=["read"])
        with pytest.raises(InsufficientScopeError) as exc_info:
            auth_manager.validate_token(token.token, required_scopes=["write"])
        assert "write" in exc_info.value.required

    def test_validate_expired_token_raises(self, auth_manager: AuthManager) -> None:
        token = auth_manager.issue_token(
            issuer="a",
            subject="b",
            scopes=["read"],
            ttl=timedelta(seconds=-1),
        )
        with pytest.raises(TokenExpiredError):
            auth_manager.validate_token(token.token)

    def test_validate_invalid_token_raises(self, auth_manager: AuthManager) -> None:
        with pytest.raises(AuthError):
            auth_manager.validate_token("not.a.valid.jwt")

    def test_validate_wrong_secret_raises(self) -> None:
        manager1 = AuthManager(secret="a" * 32)
        manager2 = AuthManager(secret="b" * 32)
        token = manager1.issue_token(issuer="a", subject="b", scopes=["read"])
        with pytest.raises(AuthError):
            manager2.validate_token(token.token)


class TestTokenRevocation:
    """Tests for token revocation."""

    def test_revoke_token(self, auth_manager: AuthManager) -> None:
        token = auth_manager.issue_token(issuer="a", subject="b", scopes=["read"])
        auth_manager.revoke_token(token.token)
        with pytest.raises(AuthError, match="revoked"):
            auth_manager.validate_token(token.token)

    def test_revoke_invalid_token_raises(self, auth_manager: AuthManager) -> None:
        with pytest.raises(AuthError):
            auth_manager.revoke_token("garbage")


class TestAuditLog:
    """Tests for the audit log."""

    def test_audit_log_ordering(self, auth_manager: AuthManager) -> None:
        auth_manager.issue_token(issuer="a", subject="b", scopes=["read"])
        auth_manager.issue_token(issuer="c", subject="d", scopes=["write"])
        log = auth_manager.get_audit_log(limit=10)
        # Most recent first
        assert log[0].issuer == "c"
        assert log[1].issuer == "a"

    def test_audit_log_limit(self, auth_manager: AuthManager) -> None:
        for i in range(20):
            auth_manager.issue_token(issuer=f"agent-{i}", subject="b", scopes=["read"])
        log = auth_manager.get_audit_log(limit=5)
        assert len(log) == 5

    def test_audit_log_tracks_failures(self, auth_manager: AuthManager) -> None:
        with contextlib.suppress(AuthError):
            auth_manager.validate_token("bad-token")
        log = auth_manager.get_audit_log()
        failed = [e for e in log if not e.success]
        assert len(failed) == 1
        assert failed[0].action == "token_validation_failed"
