import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any, Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from app.core.settings import TicketAnalysisSettings
from app.schemas.retrieval import RetrievedPassage
from app.schemas.tickets import TicketAnalysisRequest, TicketAnalysisResponse
from app.services.knowledge import (
    KnowledgeRetriever,
    LocalKnowledgeRetriever,
    VertexRagKnowledgeRetriever,
    parse_rag_corpus_resource_name,
)
from app.services.ticket_analysis import (
    GeminiTicketAnalysisService,
    MockTicketAnalysisService,
    TicketAnalysisService,
)

DEFAULT_DATASET = Path("evaluation/data/support_cases.jsonl")
DEFAULT_OUTPUT = Path("evaluation/results/latest.json")
DEFAULT_REPORT = Path("evaluation/results/latest.md")
DEFAULT_THRESHOLDS = {
    "category_accuracy": 0.0,
    "priority_accuracy": 0.0,
    "escalation_accuracy": 0.0,
    "retrieval_top1_accuracy": 0.0,
    "schema_validity_rate": 1.0,
    "prohibited_claim_pass_rate": 1.0,
}

Provider = Literal["mock", "gemini"]
KnowledgeProvider = Literal["none", "local", "vertex_rag"]


class EvaluationCase(BaseModel):
    case_id: str
    subject: str
    description: str
    channel: str
    expected_category: str
    expected_priority: str
    expected_escalation: bool
    expected_source_name: str | None = None
    prohibited_claims: list[str] = Field(default_factory=list)
    notes: str = ""


class JudgeScores(BaseModel):
    groundedness: int = Field(ge=1, le=5)
    usefulness: int = Field(ge=1, le=5)
    professionalism: int = Field(ge=1, le=5)
    notes: str = ""


@dataclass(frozen=True)
class EvaluationConfig:
    provider: Provider
    knowledge_provider: KnowledgeProvider
    dataset_path: Path
    output_path: Path
    report_path: Path
    limit: int | None
    fail_on_threshold: bool
    thresholds: dict[str, float]
    gemini_judge: bool


def load_dataset(path: Path, *, limit: int | None = None) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(EvaluationCase.model_validate_json(line))
        except ValidationError as exc:
            raise ValueError(f"Invalid evaluation case on line {line_number}.") from exc
        if limit is not None and len(cases) >= limit:
            break
    return cases


async def run_evaluation(config: EvaluationConfig) -> dict[str, Any]:
    cases = load_dataset(config.dataset_path, limit=config.limit)
    settings = TicketAnalysisSettings.from_env()
    retriever = build_retriever(config.knowledge_provider, settings)
    service = build_service(config.provider, settings, retriever)
    judge = build_judge(settings) if config.gemini_judge else None

    started_at = datetime.now(UTC)
    case_results = []
    for case in cases:
        case_results.append(
            await evaluate_case(
                case,
                service=service,
                retriever=retriever,
                judge=judge,
            )
        )

    metrics = calculate_metrics(case_results)
    threshold_results = evaluate_thresholds(metrics, config.thresholds)
    payload: dict[str, Any] = {
        "timestamp": started_at.isoformat(),
        "run_configuration": {
            "provider": config.provider,
            "knowledge_provider": config.knowledge_provider,
            "dataset": str(config.dataset_path),
            "limit": config.limit,
            "gemini_judge_enabled": config.gemini_judge,
            "judge_results_are_model_based": config.gemini_judge,
        },
        "provider_info": {
            "gemini_model": settings.gemini_model
            if config.provider == "gemini"
            else None,
            "rag_corpus_resource_name": (
                settings.rag_corpus_resource_name
                if config.knowledge_provider == "vertex_rag"
                else None
            ),
        },
        "metrics": metrics,
        "thresholds": threshold_results,
        "failed_cases": [
            result for result in case_results if not result["checks"]["overall_passed"]
        ],
        "cases": case_results,
    }
    write_outputs(payload, config.output_path, config.report_path)
    return payload


async def evaluate_case(
    case: EvaluationCase,
    *,
    service: TicketAnalysisService,
    retriever: KnowledgeRetriever | None,
    judge: "GeminiJudge | None",
) -> dict[str, Any]:
    request = TicketAnalysisRequest(
        ticket_id=case.case_id,
        subject=case.subject,
        description=case.description,
        channel=case.channel,
    )
    retrieved_passages: list[RetrievedPassage] = []
    if retriever is not None:
        retrieved_passages = await retriever.retrieve(request)

    started = time.perf_counter()
    schema_valid = True
    error: str | None = None
    response: TicketAnalysisResponse | None = None
    try:
        response = await service.analyze(request)
    except Exception as exc:
        schema_valid = False
        error = type(exc).__name__
    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    checks = evaluate_groundedness(case, response, retrieved_passages)
    if not schema_valid:
        checks["overall_passed"] = False
    judge_result = None
    if judge is not None and response is not None:
        judge_result = await judge.score(case, response, retrieved_passages)

    return {
        "case_id": case.case_id,
        "expected": {
            "category": case.expected_category,
            "priority": case.expected_priority,
            "escalation": case.expected_escalation,
            "source_name": case.expected_source_name,
        },
        "actual": response.model_dump(mode="json") if response is not None else None,
        "schema_valid": schema_valid,
        "error": error,
        "latency_ms": latency_ms,
        "retrieved_sources": [
            {
                "source_name": passage.source_name,
                "relevance_score": passage.relevance_score,
            }
            for passage in retrieved_passages
        ],
        "retrieval_diagnostics": retrieval_diagnostics(case, retrieved_passages),
        "checks": checks,
        "judge": judge_result,
    }


def build_service(
    provider: Provider,
    settings: TicketAnalysisSettings,
    retriever: KnowledgeRetriever | None,
) -> TicketAnalysisService:
    if provider == "mock":
        return MockTicketAnalysisService()
    return GeminiTicketAnalysisService(
        project=settings.google_cloud_project or "",
        location=settings.google_cloud_location,
        model=settings.gemini_model,
        knowledge_retriever=retriever,
    )


def build_retriever(
    knowledge_provider: KnowledgeProvider,
    settings: TicketAnalysisSettings,
) -> KnowledgeRetriever | None:
    if knowledge_provider == "none":
        return None
    if knowledge_provider == "local":
        return LocalKnowledgeRetriever()
    if settings.rag_corpus_resource_name is None:
        raise ValueError(
            "RAG_CORPUS_RESOURCE_NAME is required for vertex_rag evaluation."
        )
    parsed_project, parsed_location = parse_rag_corpus_resource_name(
        settings.rag_corpus_resource_name
    )
    return VertexRagKnowledgeRetriever(
        corpus_resource_name=settings.rag_corpus_resource_name,
        project=settings.google_cloud_project or parsed_project,
        location=settings.rag_location or parsed_location,
        top_k=settings.rag_top_k,
        distance_threshold=settings.rag_distance_threshold,
    )


def calculate_metrics(case_results: list[dict[str, Any]]) -> dict[str, float]:
    total = len(case_results)
    source_expected = [
        result
        for result in case_results
        if result["expected"]["source_name"] is not None
    ]
    no_source_expected = [
        result for result in case_results if result["expected"]["source_name"] is None
    ]
    latencies = [float(result["latency_ms"]) for result in case_results]

    return {
        "case_count": float(total),
        "category_accuracy": _rate(case_results, "category_correct"),
        "priority_accuracy": _rate(case_results, "priority_correct"),
        "escalation_accuracy": _rate(case_results, "escalation_correct"),
        "schema_validity_rate": _fraction(
            sum(1 for result in case_results if result["schema_valid"]),
            total,
        ),
        "retrieval_hit_rate": _rate(source_expected, "retrieval_hit"),
        "expected_source_top1_accuracy": _rate(source_expected, "source_top1_correct"),
        "no_result_correctness": _rate(no_source_expected, "no_result_correct"),
        "prohibited_claim_pass_rate": _rate(case_results, "prohibited_claims_absent"),
        "groundedness_pass_rate": _rate(case_results, "overall_passed"),
        "mean_latency_ms": round(mean(latencies), 2) if latencies else 0.0,
        "p95_latency_ms": percentile(latencies, 95),
    }


def evaluate_groundedness(
    case: EvaluationCase,
    response: TicketAnalysisResponse | None,
    retrieved_passages: list[RetrievedPassage],
) -> dict[str, bool]:
    actual_category = response.category if response is not None else None
    actual_priority = response.priority.value if response is not None else None
    actual_escalation = response.requires_escalation if response is not None else None
    suggested_response = response.suggested_response if response is not None else ""

    retrieval_hit = source_matches(retrieved_passages, case.expected_source_name)
    source_top1_correct = top1_source_matches(
        retrieved_passages,
        case.expected_source_name,
    )
    no_result_correct = (
        len(retrieved_passages) == 0 if case.expected_source_name is None else True
    )
    prohibited_claims_absent = not contains_prohibited_claim(
        suggested_response,
        case.prohibited_claims,
    )
    no_knowledge_no_procedure = no_knowledge_response_is_safe(
        case,
        suggested_response,
    )

    checks = {
        "category_correct": actual_category == case.expected_category,
        "priority_correct": actual_priority == case.expected_priority,
        "escalation_correct": actual_escalation == case.expected_escalation,
        "retrieval_hit": retrieval_hit,
        "source_top1_correct": source_top1_correct,
        "no_result_correct": no_result_correct,
        "prohibited_claims_absent": prohibited_claims_absent,
        "no_knowledge_no_procedure": no_knowledge_no_procedure,
    }
    checks["overall_passed"] = all(checks.values())
    return checks


def source_matches(
    retrieved_passages: list[RetrievedPassage],
    expected_source_name: str | None,
) -> bool:
    if expected_source_name is None:
        return len(retrieved_passages) == 0
    return any(
        passage.source_name == expected_source_name for passage in retrieved_passages
    )


def top1_source_matches(
    retrieved_passages: list[RetrievedPassage],
    expected_source_name: str | None,
) -> bool:
    if expected_source_name is None:
        return len(retrieved_passages) == 0
    if not retrieved_passages:
        return False
    return retrieved_passages[0].source_name == expected_source_name


def contains_prohibited_claim(text: str, prohibited_claims: list[str]) -> bool:
    normalized = text.lower()
    return any(claim.lower() in normalized for claim in prohibited_claims)


def no_knowledge_response_is_safe(
    case: EvaluationCase, suggested_response: str
) -> bool:
    if case.expected_source_name is not None:
        return True
    risky_terms = (
        "account recovery workflow",
        "password reset flow",
        "billing operations",
        "refund is approved",
        "incident response",
        "root cause",
    )
    normalized = suggested_response.lower()
    return not any(term in normalized for term in risky_terms)


def retrieval_diagnostics(
    case: EvaluationCase,
    retrieved_passages: list[RetrievedPassage],
) -> dict[str, bool | float | int | None]:
    return {
        "top_score": (
            retrieved_passages[0].relevance_score if retrieved_passages else None
        ),
        "retrieved_count": len(retrieved_passages),
        "expected_no_result": case.expected_source_name is None,
        "actual_no_result": len(retrieved_passages) == 0,
    }


def percentile(values: list[float], percentile_value: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = (percentile_value / 100) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * weight, 2)


def evaluate_thresholds(
    metrics: dict[str, float],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    results = {}
    for metric_name, threshold in thresholds.items():
        actual = metrics.get(metric_name, 0.0)
        results[metric_name] = {
            "threshold": threshold,
            "actual": actual,
            "passed": actual >= threshold,
        }
    return {
        "passed": all(result["passed"] for result in results.values()),
        "metrics": results,
    }


def write_outputs(
    payload: dict[str, Any],
    output_path: Path,
    report_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    report_path.write_text(render_markdown_report(payload))


def render_markdown_report(payload: dict[str, Any]) -> str:
    metrics = payload["metrics"]
    failed_cases = payload["failed_cases"]
    config = payload["run_configuration"]
    lines = [
        "# Evaluation Summary",
        "",
        f"- Timestamp: `{payload['timestamp']}`",
        f"- Provider: `{config['provider']}`",
        f"- Knowledge provider: `{config['knowledge_provider']}`",
        f"- Dataset: `{config['dataset']}`",
        f"- Gemini judge enabled: `{config['gemini_judge_enabled']}`",
        "",
        "## Aggregate Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key, value in metrics.items():
        lines.append(f"| `{key}` | {value} |")

    lines.extend(["", "## Failed Cases", ""])
    if not failed_cases:
        lines.append("No failed cases.")
    else:
        lines.extend(
            ["| Case ID | Failed Checks | Latency ms |", "| --- | --- | ---: |"]
        )
        for case in failed_cases:
            failed_checks = [
                check for check, passed in case["checks"].items() if not passed
            ]
            lines.append(
                f"| `{case['case_id']}` | {', '.join(failed_checks)} | "
                f"{case['latency_ms']} |"
            )

    lines.extend(["", "## Per-Case Latency", "", "| Case ID | Latency ms |"])
    lines.append("| --- | ---: |")
    for case in payload["cases"]:
        lines.append(f"| `{case['case_id']}` | {case['latency_ms']} |")
    lines.append("")
    return "\n".join(lines)


class GeminiJudge:
    def __init__(self, *, project: str, location: str, model: str) -> None:
        self._model = model
        self._client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            http_options=types.HttpOptions(api_version="v1"),
        ).aio.models

    async def score(
        self,
        case: EvaluationCase,
        response: TicketAnalysisResponse,
        retrieved_passages: list[RetrievedPassage],
    ) -> dict[str, Any]:
        prompt = _build_judge_prompt(case, response, retrieved_passages)
        result = await self._client.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are an evaluation judge. Score only the supplied support "
                    "answer. Return JSON with groundedness, usefulness, "
                    "professionalism, and notes."
                ),
                response_mime_type="application/json",
                response_schema=JudgeScores,
                temperature=0,
                max_output_tokens=512,
            ),
        )
        parsed = getattr(result, "parsed", None)
        scores = (
            parsed
            if isinstance(parsed, JudgeScores)
            else JudgeScores.model_validate(parsed)
        )
        return scores.model_dump()


def build_judge(settings: TicketAnalysisSettings) -> GeminiJudge:
    return GeminiJudge(
        project=settings.google_cloud_project or "",
        location=settings.google_cloud_location,
        model=settings.gemini_model,
    )


def _build_judge_prompt(
    case: EvaluationCase,
    response: TicketAnalysisResponse,
    retrieved_passages: list[RetrievedPassage],
) -> str:
    sources = [
        {"source_name": passage.source_name, "content": passage.content}
        for passage in retrieved_passages
    ]
    return json.dumps(
        {
            "instruction": (
                "Score groundedness, usefulness, and professionalism from 1 to 5. "
                "This is an evaluation prompt, not the production analysis prompt."
            ),
            "case": case.model_dump(),
            "response": response.model_dump(mode="json"),
            "retrieved_passages": sources,
        }
    )


def _rate(results: list[dict[str, Any]], check_name: str) -> float:
    if not results:
        return 0.0
    return _fraction(
        sum(1 for result in results if result["checks"][check_name]),
        len(results),
    )


def _fraction(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local or live evaluation for the support copilot."
    )
    parser.add_argument("--provider", choices=("mock", "gemini"), default="mock")
    parser.add_argument(
        "--knowledge-provider",
        choices=("none", "local", "vertex_rag"),
        default="local",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--fail-on-threshold", action="store_true")
    parser.add_argument("--gemini-judge", action="store_true")
    parser.add_argument(
        "--min-category-accuracy",
        type=float,
        default=DEFAULT_THRESHOLDS["category_accuracy"],
    )
    parser.add_argument(
        "--min-priority-accuracy",
        type=float,
        default=DEFAULT_THRESHOLDS["priority_accuracy"],
    )
    parser.add_argument(
        "--min-escalation-accuracy",
        type=float,
        default=DEFAULT_THRESHOLDS["escalation_accuracy"],
    )
    parser.add_argument(
        "--min-retrieval-top1-accuracy",
        type=float,
        default=DEFAULT_THRESHOLDS["retrieval_top1_accuracy"],
    )
    parser.add_argument(
        "--min-schema-validity",
        type=float,
        default=DEFAULT_THRESHOLDS["schema_validity_rate"],
    )
    parser.add_argument(
        "--min-prohibited-claim-pass-rate",
        type=float,
        default=DEFAULT_THRESHOLDS["prohibited_claim_pass_rate"],
    )
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> EvaluationConfig:
    thresholds = {
        "category_accuracy": args.min_category_accuracy,
        "priority_accuracy": args.min_priority_accuracy,
        "escalation_accuracy": args.min_escalation_accuracy,
        "retrieval_top1_accuracy": args.min_retrieval_top1_accuracy,
        "schema_validity_rate": args.min_schema_validity,
        "prohibited_claim_pass_rate": args.min_prohibited_claim_pass_rate,
    }
    return EvaluationConfig(
        provider=args.provider,
        knowledge_provider=args.knowledge_provider,
        dataset_path=args.dataset,
        output_path=args.output,
        report_path=args.report,
        limit=args.limit,
        fail_on_threshold=args.fail_on_threshold,
        thresholds=thresholds,
        gemini_judge=args.gemini_judge,
    )


async def async_main() -> int:
    config = config_from_args(parse_args())
    payload = await run_evaluation(config)
    print(f"Wrote JSON results to {config.output_path}")
    print(f"Wrote Markdown report to {config.report_path}")
    print(json.dumps(payload["metrics"], indent=2, sort_keys=True))
    if config.fail_on_threshold and not payload["thresholds"]["passed"]:
        return 1
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
