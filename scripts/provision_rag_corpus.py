import argparse
import asyncio
import os
from collections.abc import Sequence

from app.services.knowledge import AgentPlatformRagAdapter


def main() -> None:
    args = _parse_args()
    asyncio.run(_provision(args))


async def _provision(args: argparse.Namespace) -> None:
    project = _required(args.project, "GOOGLE_CLOUD_PROJECT or --project")
    location = _required(args.location, "RAG_LOCATION or --location")
    display_name = _required(
        args.display_name, "RAG_CORPUS_DISPLAY_NAME or --display-name"
    )
    gcs_uri = _required(args.gcs_uri, "RAG_IMPORT_GCS_URI or --gcs-uri")

    adapter = AgentPlatformRagAdapter(project=project, location=location)
    existing = await adapter.list_corpora()
    corpus = _find_corpus(existing, display_name)
    if corpus is None:
        corpus = await adapter.create_corpus(display_name=display_name)

    corpus_name = _string_field(corpus, "name")
    if corpus_name is None:
        raise RuntimeError("RAG corpus response did not include a resource name.")

    await adapter.import_files(corpus_resource_name=corpus_name, gcs_uri=gcs_uri)
    print(corpus_name)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or reuse a Vertex AI RAG corpus and import GCS files."
    )
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument(
        "--location",
        default=os.getenv("RAG_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION"),
    )
    parser.add_argument("--display-name", default=os.getenv("RAG_CORPUS_DISPLAY_NAME"))
    parser.add_argument("--gcs-uri", default=os.getenv("RAG_IMPORT_GCS_URI"))
    return parser.parse_args()


def _find_corpus(response: object, display_name: str) -> object | None:
    corpora = _field(response, "ragCorpora")
    if not isinstance(corpora, Sequence) or isinstance(corpora, str):
        return None

    for corpus in corpora:
        if _string_field(corpus, "displayName") == display_name:
            return corpus
    return None


def _required(value: str | None, label: str) -> str:
    if value is None or not value.strip():
        raise SystemExit(f"Missing required value: {label}.")
    return value.strip()


def _string_field(value: object, name: str) -> str | None:
    field_value = _field(value, name)
    if not isinstance(field_value, str) or not field_value.strip():
        return None
    return field_value.strip()


def _field(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name) or value.get(_camel_to_snake(name))
    return getattr(value, name, None) or getattr(value, _camel_to_snake(name), None)


def _camel_to_snake(value: str) -> str:
    chars: list[str] = []
    for char in value:
        if char.isupper() and chars:
            chars.append("_")
        chars.append(char.lower())
    return "".join(chars)


if __name__ == "__main__":
    main()
