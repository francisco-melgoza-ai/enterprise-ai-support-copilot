import argparse
import asyncio
import os

from app.schemas.tickets import TicketAnalysisRequest
from app.services.knowledge import (
    AgentPlatformRagAdapter,
    VertexRagKnowledgeRetriever,
    parse_rag_corpus_resource_name,
)


def main() -> None:
    args = _parse_args()
    asyncio.run(_verify(args))


async def _verify(args: argparse.Namespace) -> None:
    corpus_resource_name = _required(
        args.corpus_resource_name,
        "RAG_CORPUS_RESOURCE_NAME or --corpus-resource-name",
    )
    query = _required(args.query, "--query")
    parsed_project, parsed_location = parse_rag_corpus_resource_name(
        corpus_resource_name
    )
    project = args.project or parsed_project
    location = args.location or parsed_location
    adapter = AgentPlatformRagAdapter(project=project, location=location)
    retriever = VertexRagKnowledgeRetriever(
        corpus_resource_name=corpus_resource_name,
        project=project,
        location=location,
        top_k=args.top_k,
        distance_threshold=args.distance_threshold,
        adapter=adapter,
    )
    passages = await retriever.retrieve(
        TicketAnalysisRequest(
            ticket_id="verification-query",
            subject=query,
            description=query,
            channel="web",
        )
    )

    if not passages:
        print("No passages retrieved.")
        return

    for index, passage in enumerate(passages, start=1):
        print(
            f"{index}. source_name={passage.source_name} "
            f"source_path={passage.source_path} "
            f"relevance_score={passage.relevance_score}"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify Vertex AI RAG retrieval without calling Gemini."
    )
    parser.add_argument(
        "--corpus-resource-name",
        default=os.getenv("RAG_CORPUS_RESOURCE_NAME"),
    )
    parser.add_argument("--query", required=True)
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument(
        "--location",
        default=os.getenv("RAG_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION"),
    )
    parser.add_argument("--top-k", type=int, default=int(os.getenv("RAG_TOP_K", "3")))
    parser.add_argument(
        "--distance-threshold",
        type=float,
        default=float(os.getenv("RAG_DISTANCE_THRESHOLD", "0.5")),
    )
    return parser.parse_args()


def _required(value: str | None, label: str) -> str:
    if value is None or not value.strip():
        raise SystemExit(f"Missing required value: {label}.")
    return value.strip()


if __name__ == "__main__":
    main()
