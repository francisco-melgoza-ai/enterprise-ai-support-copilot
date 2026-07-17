import pytest

from app.core.settings import TicketAnalysisSettings


def test_settings_load_from_temporary_dotenv(tmp_path, monkeypatch) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "TICKET_ANALYSIS_PROVIDER=gemini",
                "KNOWLEDGE_PROVIDER=local",
                "GOOGLE_CLOUD_PROJECT=test-project",
                "GOOGLE_CLOUD_LOCATION=us-east1",
                "GEMINI_MODEL=gemini-test",
                "RAG_CORPUS_RESOURCE_NAME=projects/test/locations/us-east1/ragCorpora/1",
                "RAG_LOCATION=us-east1",
                "RAG_TOP_K=5",
                "RAG_DISTANCE_THRESHOLD=0.7",
                "AUTH_PROVIDER=google",
                "AUTH_GOOGLE_AUDIENCE=https://service.example",
            ]
        )
    )
    monkeypatch.delenv("TICKET_ANALYSIS_PROVIDER", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("RAG_CORPUS_RESOURCE_NAME", raising=False)
    monkeypatch.delenv("RAG_LOCATION", raising=False)
    monkeypatch.delenv("RAG_TOP_K", raising=False)
    monkeypatch.delenv("RAG_DISTANCE_THRESHOLD", raising=False)
    monkeypatch.delenv("AUTH_PROVIDER", raising=False)
    monkeypatch.delenv("AUTH_GOOGLE_AUDIENCE", raising=False)

    settings = TicketAnalysisSettings.from_env(dotenv_path)

    assert settings.provider == "gemini"
    assert settings.knowledge_provider == "local"
    assert settings.google_cloud_project == "test-project"
    assert settings.google_cloud_location == "us-east1"
    assert settings.gemini_model == "gemini-test"
    assert settings.rag_corpus_resource_name == (
        "projects/test/locations/us-east1/ragCorpora/1"
    )
    assert settings.rag_location == "us-east1"
    assert settings.rag_top_k == 5
    assert settings.rag_distance_threshold == 0.7
    assert settings.auth_provider == "google"
    assert settings.auth_google_audience == "https://service.example"


def test_settings_load_resilience_configuration(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "11")
    monkeypatch.setenv("GEMINI_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("GEMINI_RETRY_BASE_DELAY_SECONDS", "0.5")
    monkeypatch.setenv("GEMINI_RETRY_MAX_DELAY_SECONDS", "3")
    monkeypatch.setenv("GEMINI_RETRY_JITTER_SECONDS", "0.2")
    monkeypatch.setenv("GEMINI_CIRCUIT_BREAKER_ENABLED", "false")
    monkeypatch.setenv("GEMINI_CIRCUIT_FAILURE_THRESHOLD", "7")
    monkeypatch.setenv("GEMINI_CIRCUIT_RECOVERY_SECONDS", "20")
    monkeypatch.setenv("GEMINI_CIRCUIT_HALF_OPEN_MAX_CALLS", "2")
    monkeypatch.setenv("RAG_GRACEFUL_DEGRADATION_ENABLED", "false")

    settings = TicketAnalysisSettings.from_env()

    assert settings.gemini_resilience.timeout.timeout_seconds == 11
    assert settings.gemini_resilience.retry.max_attempts == 4
    assert settings.gemini_resilience.retry.base_delay_seconds == 0.5
    assert settings.gemini_resilience.retry.max_delay_seconds == 3
    assert settings.gemini_resilience.retry.jitter_seconds == 0.2
    assert not settings.gemini_resilience.circuit_breaker.enabled
    assert settings.gemini_resilience.circuit_breaker.failure_threshold == 7
    assert settings.gemini_resilience.circuit_breaker.recovery_timeout_seconds == 20
    assert settings.gemini_resilience.circuit_breaker.half_open_max_calls == 2
    assert not settings.rag_graceful_degradation_enabled


def test_settings_reject_invalid_resilience_configuration(monkeypatch) -> None:
    monkeypatch.setenv("RAG_RETRY_BASE_DELAY_SECONDS", "2")
    monkeypatch.setenv("RAG_RETRY_MAX_DELAY_SECONDS", "1")

    with pytest.raises(ValueError):
        TicketAnalysisSettings.from_env()


def test_settings_reject_unsupported_auth_provider(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_PROVIDER", "unsupported")

    with pytest.raises(ValueError):
        TicketAnalysisSettings.from_env()


def test_settings_load_conversation_configuration(monkeypatch) -> None:
    monkeypatch.setenv("CONVERSATION_TTL_SECONDS", "7200")
    monkeypatch.setenv("CONVERSATION_SUMMARY_THRESHOLD", "9")
    monkeypatch.setenv("CONVERSATION_MAX_RECENT_MESSAGES", "4")

    settings = TicketAnalysisSettings.from_env()

    assert settings.conversation_ttl_seconds == 7200
    assert settings.conversation_summary_threshold == 9
    assert settings.conversation_max_recent_messages == 4


def test_settings_reject_invalid_conversation_configuration(monkeypatch) -> None:
    monkeypatch.setenv("CONVERSATION_TTL_SECONDS", "0")

    with pytest.raises(ValueError):
        TicketAnalysisSettings.from_env()


def test_settings_require_summary_threshold_above_recent_messages(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CONVERSATION_SUMMARY_THRESHOLD", "4")
    monkeypatch.setenv("CONVERSATION_MAX_RECENT_MESSAGES", "4")

    with pytest.raises(ValueError):
        TicketAnalysisSettings.from_env()
