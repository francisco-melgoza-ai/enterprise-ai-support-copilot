import os
from dataclasses import dataclass

DEFAULT_TICKET_ANALYSIS_PROVIDER = "mock"
DEFAULT_GOOGLE_CLOUD_LOCATION = "us-central1"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


@dataclass(frozen=True)
class TicketAnalysisSettings:
    provider: str
    google_cloud_project: str | None
    google_cloud_location: str
    gemini_model: str

    @classmethod
    def from_env(cls) -> "TicketAnalysisSettings":
        return cls(
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
