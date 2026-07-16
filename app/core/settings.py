import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_TICKET_ANALYSIS_PROVIDER = "mock"
DEFAULT_GOOGLE_CLOUD_LOCATION = "us-central1"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_APP_ENV = "local"


@dataclass(frozen=True)
class TicketAnalysisSettings:
    app_env: str
    provider: str
    google_cloud_project: str | None
    google_cloud_location: str
    gemini_model: str

    @classmethod
    def from_env(
        cls, dotenv_path: str | Path | None = None
    ) -> "TicketAnalysisSettings":
        load_dotenv(dotenv_path=dotenv_path, override=False)

        return cls(
            app_env=os.getenv("APP_ENV", DEFAULT_APP_ENV).strip() or DEFAULT_APP_ENV,
            provider=os.getenv(
                "TICKET_ANALYSIS_PROVIDER", DEFAULT_TICKET_ANALYSIS_PROVIDER
            ).strip()
            or DEFAULT_TICKET_ANALYSIS_PROVIDER,
            google_cloud_project=_optional_env("GOOGLE_CLOUD_PROJECT"),
            google_cloud_location=os.getenv(
                "GOOGLE_CLOUD_LOCATION", DEFAULT_GOOGLE_CLOUD_LOCATION
            ).strip()
            or DEFAULT_GOOGLE_CLOUD_LOCATION,
            gemini_model=os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
            or DEFAULT_GEMINI_MODEL,
        )


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
