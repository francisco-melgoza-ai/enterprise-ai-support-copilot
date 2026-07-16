import pytest

from app.api.dependencies.services import get_ticket_analysis_service
from app.services.ticket_analysis import (
    GeminiTicketAnalysisService,
    MockTicketAnalysisService,
    TicketAnalysisConfigurationError,
)


def test_provider_defaults_blank_value_to_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TICKET_ANALYSIS_PROVIDER", "")
    get_ticket_analysis_service.cache_clear()

    service = get_ticket_analysis_service()

    assert isinstance(service, MockTicketAnalysisService)


def test_provider_selects_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TICKET_ANALYSIS_PROVIDER", "mock")
    get_ticket_analysis_service.cache_clear()

    service = get_ticket_analysis_service()

    assert isinstance(service, MockTicketAnalysisService)


def test_provider_selects_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TICKET_ANALYSIS_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    get_ticket_analysis_service.cache_clear()

    service = get_ticket_analysis_service()

    assert isinstance(service, GeminiTicketAnalysisService)


def test_provider_rejects_unsupported_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TICKET_ANALYSIS_PROVIDER", "unsupported")
    get_ticket_analysis_service.cache_clear()

    with pytest.raises(TicketAnalysisConfigurationError):
        get_ticket_analysis_service()
