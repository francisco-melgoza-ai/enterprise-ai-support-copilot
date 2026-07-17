import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, cast

from app.core.metrics import record_authentication_request
from app.core.settings import TicketAnalysisSettings
from app.core.tracing import get_tracer, record_span_exception, set_span_attributes

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)

SUPPORTED_AUTH_PROVIDERS = {"mock", "google"}
MOCK_TOKEN_PREFIX = "mock"


class SupportRole(StrEnum):
    SUPPORT_AGENT = "support_agent"
    SUPPORT_MANAGER = "support_manager"
    PLATFORM_ADMIN = "platform_admin"


ALL_SUPPORT_ROLES = frozenset(role.value for role in SupportRole)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    subject: str
    email: str | None
    roles: frozenset[str]
    provider: str


class AuthenticationError(Exception):
    """Raised when authentication fails safely."""


class AuthorizationError(Exception):
    """Raised when a principal lacks a required role."""


class AuthenticationConfigurationError(ValueError):
    """Raised when authentication is configured incorrectly."""


class AuthenticationProvider(Protocol):
    provider_name: str

    async def authenticate(self, bearer_token: str) -> AuthenticatedPrincipal:
        """Authenticate a bearer token into a normalized principal."""


class GoogleTokenVerifier(Protocol):
    def verify(self, token: str, audience: str) -> Mapping[str, Any]:
        """Verify a Google-issued OIDC token and return verified claims."""


class MockAuthenticationProvider:
    provider_name = "mock"

    def __init__(self, *, settings: TicketAnalysisSettings) -> None:
        if settings.app_env.lower() == "production":
            if not settings.auth_mock_allow_in_production:
                raise AuthenticationConfigurationError(
                    "Mock authentication is blocked in production unless "
                    "AUTH_MOCK_ALLOW_IN_PRODUCTION=true."
                )
            logger.warning(
                "unsafe_mock_authentication_enabled",
                extra={"auth_provider": self.provider_name, "outcome": "enabled"},
            )

    async def authenticate(self, bearer_token: str) -> AuthenticatedPrincipal:
        with tracer.start_as_current_span("auth.authenticate") as span:
            span.set_attribute("auth.provider", self.provider_name)
            try:
                principal = self._parse_token(bearer_token)
            except AuthenticationError as exc:
                _record_auth_result(provider=self.provider_name, outcome="invalid")
                record_span_exception(span, exc)
                span.set_attribute("auth.outcome", "invalid")
                raise
            _record_auth_result(provider=self.provider_name, outcome="success")
            set_span_attributes(
                span,
                {
                    "auth.outcome": "success",
                    "auth.role_count": len(principal.roles),
                },
            )
            return principal

    def _parse_token(self, bearer_token: str) -> AuthenticatedPrincipal:
        parts = bearer_token.split(":", maxsplit=2)
        if len(parts) != 3 or parts[0] != MOCK_TOKEN_PREFIX:
            raise AuthenticationError("Invalid mock bearer token.")

        subject = parts[1].strip()
        roles = _normalize_roles(parts[2].split(","))
        if not subject or not roles:
            raise AuthenticationError("Invalid mock bearer token.")

        return AuthenticatedPrincipal(
            subject=subject,
            email=None,
            roles=roles,
            provider=self.provider_name,
        )


class GoogleOidcAuthenticationProvider:
    provider_name = "google"

    def __init__(
        self,
        *,
        audience: str | None,
        verifier: GoogleTokenVerifier | None = None,
    ) -> None:
        if audience is None or not audience.strip():
            raise AuthenticationConfigurationError(
                "AUTH_GOOGLE_AUDIENCE is required when AUTH_PROVIDER=google."
            )
        self._audience = audience.strip()
        self._verifier = verifier or GoogleAuthTokenVerifier()

    async def authenticate(self, bearer_token: str) -> AuthenticatedPrincipal:
        with tracer.start_as_current_span("auth.authenticate") as span:
            span.set_attribute("auth.provider", self.provider_name)
            try:
                claims = self._verifier.verify(bearer_token, self._audience)
                principal = self._principal_from_claims(claims)
            except AuthenticationError as exc:
                _record_auth_result(provider=self.provider_name, outcome="invalid")
                record_span_exception(span, exc)
                span.set_attribute("auth.outcome", "invalid")
                raise
            except Exception as exc:
                auth_error = AuthenticationError("Google token validation failed.")
                _record_auth_result(provider=self.provider_name, outcome="invalid")
                record_span_exception(span, auth_error)
                span.set_attribute("auth.outcome", "invalid")
                raise auth_error from exc

            _record_auth_result(provider=self.provider_name, outcome="success")
            set_span_attributes(
                span,
                {
                    "auth.outcome": "success",
                    "auth.role_count": len(principal.roles),
                },
            )
            return principal

    def _principal_from_claims(
        self, claims: Mapping[str, Any]
    ) -> AuthenticatedPrincipal:
        subject = _claim_string(claims, "sub")
        if subject is None:
            raise AuthenticationError("Google token is missing subject.")

        roles = _roles_from_claims(claims)
        return AuthenticatedPrincipal(
            subject=subject,
            email=_claim_string(claims, "email"),
            roles=roles,
            provider=self.provider_name,
        )


class GoogleAuthTokenVerifier:
    def verify(self, token: str, audience: str) -> Mapping[str, Any]:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            token,
            google_requests.Request(),
            audience,
        )
        return cast(Mapping[str, Any], claims)


def build_authentication_provider(
    settings: TicketAnalysisSettings,
) -> AuthenticationProvider:
    provider = settings.auth_provider.lower()
    if provider == "mock":
        return MockAuthenticationProvider(settings=settings)
    if provider == "google":
        return GoogleOidcAuthenticationProvider(audience=settings.auth_google_audience)
    raise AuthenticationConfigurationError(
        "Unsupported AUTH_PROVIDER. Expected 'mock' or 'google'."
    )


def validate_auth_provider(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_AUTH_PROVIDERS:
        raise ValueError("AUTH_PROVIDER must be one of: mock, google.")
    return normalized


def _roles_from_claims(claims: Mapping[str, Any]) -> frozenset[str]:
    roles_claim = claims.get("roles", claims.get("role", ()))
    if isinstance(roles_claim, str):
        raw_roles = roles_claim.split(",")
    elif isinstance(roles_claim, list | tuple | set):
        raw_roles = [str(role) for role in roles_claim]
    else:
        raw_roles = []
    return _normalize_roles(raw_roles)


def _normalize_roles(raw_roles: list[str]) -> frozenset[str]:
    roles: set[str] = set()
    for raw_role in raw_roles:
        role = raw_role.strip().lower()
        if not role or role not in ALL_SUPPORT_ROLES:
            raise AuthenticationError("Token contains unsupported role.")
        roles.add(role)
    return frozenset(roles)


def _claim_string(claims: Mapping[str, Any], key: str) -> str | None:
    value = claims.get(key)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _record_auth_result(*, provider: str, outcome: str) -> None:
    record_authentication_request(provider=provider, outcome=outcome)
    logger.info(
        "authentication_completed",
        extra={"auth_provider": provider, "outcome": outcome},
    )
