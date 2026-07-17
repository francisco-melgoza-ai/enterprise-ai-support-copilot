import logging
from collections.abc import Awaitable, Callable, Iterable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header
from opentelemetry import trace

from app.core.auth import (
    ALL_SUPPORT_ROLES,
    AuthenticatedPrincipal,
    AuthenticationError,
    AuthenticationProvider,
    AuthorizationError,
    build_authentication_provider,
)
from app.core.metrics import record_authorization_request
from app.core.settings import TicketAnalysisSettings

logger = logging.getLogger(__name__)


@lru_cache
def get_authentication_provider() -> AuthenticationProvider:
    settings = TicketAnalysisSettings.from_env()
    return build_authentication_provider(settings)


AUTHENTICATION_PROVIDER_DEPENDENCY = Depends(get_authentication_provider)


async def get_authenticated_principal(
    authorization: Annotated[str | None, Header()] = None,
    provider: AuthenticationProvider = AUTHENTICATION_PROVIDER_DEPENDENCY,
) -> AuthenticatedPrincipal:
    bearer_token = _bearer_token(authorization)
    return await provider.authenticate(bearer_token)


def require_role(
    role: str,
) -> Callable[[AuthenticatedPrincipal], Awaitable[AuthenticatedPrincipal]]:
    return require_any_role({role})


def require_any_role(
    roles: Iterable[str],
) -> Callable[[AuthenticatedPrincipal], Awaitable[AuthenticatedPrincipal]]:
    required_roles = frozenset(_normalize_required_roles(roles))

    async def dependency(
        principal: Annotated[
            AuthenticatedPrincipal,
            Depends(get_authenticated_principal),
        ],
    ) -> AuthenticatedPrincipal:
        span = trace.get_current_span()
        allowed = bool(principal.roles.intersection(required_roles))
        outcome = "success" if allowed else "forbidden"
        record_authorization_request(outcome=outcome)
        if span.is_recording():
            span.set_attribute("authz.outcome", outcome)
            span.set_attribute("authz.required_role_count", len(required_roles))
            span.set_attribute("authz.principal_role_count", len(principal.roles))
        logger.info(
            "authorization_completed",
            extra={
                "authorization_outcome": outcome,
                "roles": sorted(principal.roles),
                "auth_provider": principal.provider,
            },
        )
        if not allowed:
            raise AuthorizationError("Insufficient role.")
        return principal

    return dependency


def _bearer_token(authorization: str | None) -> str:
    if authorization is None or not authorization.strip():
        raise AuthenticationError("Missing bearer token.")

    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("Malformed bearer token.")
    return token.strip()


def _normalize_required_roles(roles: Iterable[str]) -> list[str]:
    normalized = [role.strip().lower() for role in roles]
    invalid = [role for role in normalized if role not in ALL_SUPPORT_ROLES]
    if invalid:
        raise ValueError("Required roles must be known support roles.")
    return normalized
