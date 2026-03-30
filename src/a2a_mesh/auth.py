"""Authentication and authorization manager for a2a-mesh.

Handles JWT-based token exchange between agents, scope management, and
audit logging. Each token carries scoped claims that restrict what the
bearer agent is permitted to do.
"""

from __future__ import annotations

import secrets
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta

import jwt

from a2a_mesh._logging import get_logger
from a2a_mesh.exceptions import (
    AuthError,
    InsufficientScopeError,
    TokenExpiredError,
)
from a2a_mesh.models import AuditEntry, ScopedToken

logger = get_logger(__name__)

# Default token lifetime
_DEFAULT_TTL = timedelta(hours=1)


class AuthManager:
    """Manages agent-to-agent authentication via scoped JWT tokens.

    The auth manager issues, validates, and revokes tokens. Every
    operation is recorded in an append-only audit log.

    Attributes:
        secret: The signing secret for JWTs.
        algorithm: JWT signing algorithm.
        default_ttl: Default token lifetime.
        audit_log: Chronological list of audit entries.
    """

    def __init__(
        self,
        secret: str | None = None,
        algorithm: str = "HS256",
        default_ttl: timedelta = _DEFAULT_TTL,
        max_revoked_tokens: int = 10_000,
    ) -> None:
        """Initialize the auth manager.

        Args:
            secret: Signing secret. Auto-generated if not provided.
            algorithm: JWT algorithm (default HS256).
            default_ttl: Default token lifetime.
            max_revoked_tokens: Maximum number of revoked token IDs to
                retain. When exceeded, the oldest entries are evicted.
        """
        self.secret = secret or secrets.token_urlsafe(32)
        self.algorithm = algorithm
        self.default_ttl = default_ttl
        self.max_revoked_tokens = max_revoked_tokens
        self.audit_log: list[AuditEntry] = []
        self._revoked: OrderedDict[str, float] = OrderedDict()

    def issue_token(
        self,
        issuer: str,
        subject: str,
        scopes: list[str],
        ttl: timedelta | None = None,
    ) -> ScopedToken:
        """Issue a scoped JWT token.

        The issuer delegates a subset of its permissions to the subject
        by encoding the allowed scopes in the token claims.

        Args:
            issuer: Agent issuing the token.
            subject: Agent the token is issued to.
            scopes: List of permitted scopes.
            ttl: Token lifetime. Uses default_ttl if not provided.

        Returns:
            A ScopedToken containing the encoded JWT.
        """
        now = datetime.now(UTC)
        exp = now + (ttl or self.default_ttl)

        claims = {
            "iss": issuer,
            "sub": subject,
            "scopes": scopes,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "jti": secrets.token_hex(8),
        }

        encoded = jwt.encode(claims, self.secret, algorithm=self.algorithm)

        token = ScopedToken(
            token=encoded,
            issuer=issuer,
            subject=subject,
            scopes=scopes,
            issued_at=now,
            expires_at=exp,
        )

        self._audit(
            issuer=issuer,
            subject=subject,
            action="token_issued",
            scopes=scopes,
            success=True,
        )

        logger.info(
            "auth.token_issued",
            issuer=issuer,
            subject=subject,
            scopes=scopes,
        )
        return token

    def validate_token(
        self,
        token: str,
        required_scopes: list[str] | None = None,
    ) -> dict[str, object]:
        """Validate a JWT token and optionally check scopes.

        Args:
            token: The encoded JWT string.
            required_scopes: Scopes that must be present in the token.

        Returns:
            The decoded token claims.

        Raises:
            TokenExpiredError: If the token has expired.
            InsufficientScopeError: If the token lacks required scopes.
            AuthError: If the token is invalid or revoked.
        """
        try:
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=[self.algorithm],
            )
        except jwt.ExpiredSignatureError as exc:
            self._audit(
                action="token_validation_failed",
                detail="expired",
                success=False,
            )
            raise TokenExpiredError() from exc
        except jwt.InvalidTokenError as exc:
            self._audit(
                action="token_validation_failed",
                detail=str(exc),
                success=False,
            )
            raise AuthError(f"Invalid token: {exc}") from exc

        jti = claims.get("jti", "")
        if jti in self._revoked:
            self._audit(
                action="token_validation_failed",
                detail="revoked",
                success=False,
            )
            raise AuthError("Token has been revoked")

        if required_scopes:
            token_scopes = claims.get("scopes", [])
            missing = [s for s in required_scopes if s not in token_scopes]
            if missing:
                self._audit(
                    issuer=str(claims.get("iss", "")),
                    subject=str(claims.get("sub", "")),
                    action="scope_check_failed",
                    scopes=required_scopes,
                    success=False,
                )
                raise InsufficientScopeError(required_scopes, token_scopes)

        self._audit(
            issuer=str(claims.get("iss", "")),
            subject=str(claims.get("sub", "")),
            action="token_validated",
            scopes=claims.get("scopes", []),
            success=True,
        )
        return claims

    def revoke_token(self, token: str) -> None:
        """Revoke a token so it can no longer be used.

        Args:
            token: The encoded JWT to revoke.
        """
        try:
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=[self.algorithm],
                options={"verify_exp": False},
            )
            jti = claims.get("jti", "")
            self._revoked[jti] = time.monotonic()
            # Evict oldest entries when the revocation list exceeds the cap
            while len(self._revoked) > self.max_revoked_tokens:
                self._revoked.popitem(last=False)
            self._audit(
                issuer=str(claims.get("iss", "")),
                subject=str(claims.get("sub", "")),
                action="token_revoked",
                success=True,
            )
            logger.info("auth.token_revoked", jti=jti)
        except jwt.InvalidTokenError as exc:
            raise AuthError(f"Cannot revoke invalid token: {exc}") from exc

    def get_audit_log(self, limit: int = 100) -> list[AuditEntry]:
        """Return the most recent audit log entries.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of audit entries, most recent first.
        """
        return list(reversed(self.audit_log[-limit:]))

    def _audit(
        self,
        *,
        issuer: str = "",
        subject: str = "",
        action: str = "",
        scopes: list[str] | None = None,
        success: bool = True,
        detail: str = "",
    ) -> None:
        """Append an entry to the audit log."""
        entry = AuditEntry(
            issuer=issuer,
            subject=subject,
            action=action,
            scopes=scopes or [],
            success=success,
            detail=detail,
        )
        self.audit_log.append(entry)
