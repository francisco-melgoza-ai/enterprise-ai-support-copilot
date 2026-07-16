from pydantic import BaseModel, Field


class RetrievedPassage(BaseModel):
    content: str
    source_name: str
    source_path: str
    relevance_score: float = Field(ge=0)
