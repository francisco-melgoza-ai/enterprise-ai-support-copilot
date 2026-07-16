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
