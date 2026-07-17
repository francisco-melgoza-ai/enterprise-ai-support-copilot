import logging
from collections.abc import Mapping
from typing import Any

import pytest

from app.core.auth import (
    AuthenticationError,
    GoogleOidcAuthenticationProvider,
    MockAuthenticationProvider,
)
from app.core.settings import TicketAnalysisSettings


class FakeGoogleVerifier:
    def __init__(self, claims: Mapping[str, Any] | Exception) -> None:
        self.claims = claims
        self.calls: list[dict[str, str]] = []

    def verify(self, token: str, audience: str) -> Mapping[str, Any]:
        self.calls.append({"token": token, "audience": audience})
        if isinstance(self.claims, Exception):
            raise self.claims
        return self.claims


@pytest.mark.anyio
async def test_mock_provider_accepts_valid_agent_token() -> None:
    provider = MockAuthenticationProvider(settings=TicketAnalysisSettings.from_env())

    principal = await provider.authenticate("mock:agent-123:support_agent")

    assert principal.subject == "agent-123"
    assert principal.email is None
    assert principal.roles == frozenset({"support_agent"})
    assert principal.provider == "mock"


@pytest.mark.anyio
async def test_mock_provider_rejects_invalid_token() -> None:
    provider = MockAuthenticationProvider(settings=TicketAnalysisSettings.from_env())

    with pytest.raises(AuthenticationError):
        await provider.authenticate("not-a-valid-token")


def test_mock_provider_is_blocked_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MOCK_ALLOW_IN_PRODUCTION", "false")

    with pytest.raises(ValueError):
        MockAuthenticationProvider(settings=TicketAnalysisSettings.from_env())


def test_mock_provider_can_be_explicitly_allowed_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MOCK_ALLOW_IN_PRODUCTION", "true")

    provider = MockAuthenticationProvider(settings=TicketAnalysisSettings.from_env())

    assert provider.provider_name == "mock"


def test_mock_provider_logs_warning_for_unsafe_production_override(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MOCK_ALLOW_IN_PRODUCTION", "true")
    caplog.set_level(logging.WARNING)

    MockAuthenticationProvider(settings=TicketAnalysisSettings.from_env())

    assert "unsafe_mock_authentication_enabled" in caplog.text
    assert "mock:agent-123:support_agent" not in caplog.text


def test_settings_reject_unsupported_auth_provider(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_PROVIDER", "unknown")

    with pytest.raises(ValueError):
        TicketAnalysisSettings.from_env()


def test_google_provider_requires_audience() -> None:
    with pytest.raises(ValueError):
        GoogleOidcAuthenticationProvider(audience=None)


@pytest.mark.anyio
async def test_google_provider_accepts_verified_claims() -> None:
    verifier = FakeGoogleVerifier(
        {
            "sub": "google-subject",
            "email": "agent@example.com",
            "roles": ["support_manager"],
        }
    )
    provider = GoogleOidcAuthenticationProvider(
        audience="https://service.example",
        verifier=verifier,
    )

    principal = await provider.authenticate("signed-token")

    assert principal.subject == "google-subject"
    assert principal.email == "agent@example.com"
    assert principal.roles == frozenset({"support_manager"})
    assert principal.provider == "google"
    assert verifier.calls == [
        {"token": "signed-token", "audience": "https://service.example"}
    ]


@pytest.mark.parametrize(
    "verifier_error",
    [
        ValueError("invalid issuer"),
        ValueError("invalid audience"),
        ValueError("token expired"),
    ],
)
@pytest.mark.anyio
async def test_google_provider_rejects_verifier_failures(
    verifier_error: Exception,
) -> None:
    provider = GoogleOidcAuthenticationProvider(
        audience="https://service.example",
        verifier=FakeGoogleVerifier(verifier_error),
    )

    with pytest.raises(AuthenticationError):
        await provider.authenticate("signed-token")


@pytest.mark.anyio
async def test_google_provider_rejects_missing_subject() -> None:
    provider = GoogleOidcAuthenticationProvider(
        audience="https://service.example",
        verifier=FakeGoogleVerifier({"email": "agent@example.com"}),
    )

    with pytest.raises(AuthenticationError):
        await provider.authenticate("signed-token")


@pytest.mark.anyio
async def test_authentication_logs_do_not_include_tokens(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    provider = MockAuthenticationProvider(settings=TicketAnalysisSettings.from_env())

    await provider.authenticate("mock:agent-123:support_agent")

    assert "mock:agent-123:support_agent" not in caplog.text
    assert all(not hasattr(record, "authorization") for record in caplog.records)


@pytest.mark.anyio
async def test_mock_provider_rejects_unknown_or_empty_roles() -> None:
    provider = MockAuthenticationProvider(settings=TicketAnalysisSettings.from_env())

    with pytest.raises(AuthenticationError):
        await provider.authenticate("mock:agent-123:support_agent,unknown")
    with pytest.raises(AuthenticationError):
        await provider.authenticate("mock:agent-123:support_agent,")


@pytest.mark.anyio
async def test_mock_provider_normalizes_whitespace_and_duplicate_roles() -> None:
    provider = MockAuthenticationProvider(settings=TicketAnalysisSettings.from_env())

    principal = await provider.authenticate(
        "mock:agent-123: support_agent , support_agent "
    )

    assert principal.roles == frozenset({"support_agent"})
