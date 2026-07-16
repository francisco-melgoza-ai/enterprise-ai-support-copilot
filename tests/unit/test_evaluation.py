import json
from pathlib import Path

from app.schemas.retrieval import RetrievedPassage
from app.schemas.tickets import TicketAnalysisResponse
from evaluation.runner import (
    EvaluationCase,
    calculate_metrics,
    contains_prohibited_claim,
    evaluate_groundedness,
    evaluate_thresholds,
    load_dataset,
    no_knowledge_response_is_safe,
    percentile,
    render_markdown_report,
    retrieval_diagnostics,
    source_matches,
    top1_source_matches,
)


def test_load_dataset_reads_jsonl_cases(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "case_id": "EVAL-TEST",
                "subject": "Invoice charge",
                "description": "Billing dispute",
                "channel": "email",
                "expected_category": "billing",
                "expected_priority": "low",
                "expected_escalation": False,
                "expected_source_name": "billing_dispute_procedure.md",
                "prohibited_claims": ["refund guaranteed"],
                "notes": "synthetic",
            }
        )
    )

    cases = load_dataset(dataset)

    assert len(cases) == 1
    assert cases[0].case_id == "EVAL-TEST"
    assert cases[0].expected_source_name == "billing_dispute_procedure.md"


def test_percentile_calculation_interpolates() -> None:
    assert percentile([10, 20, 30, 40], 95) == 38.5
    assert percentile([42], 95) == 42
    assert percentile([], 95) == 0


def test_source_matching_and_no_result_correctness() -> None:
    passages = [
        RetrievedPassage(
            content="Billing procedure",
            source_name="billing_dispute_procedure.md",
            source_path="sample_data/knowledge/billing_dispute_procedure.md",
            relevance_score=0.9,
        )
    ]

    assert source_matches(passages, "billing_dispute_procedure.md")
    assert top1_source_matches(passages, "billing_dispute_procedure.md")
    assert source_matches([], None)
    assert top1_source_matches([], None)
    assert not top1_source_matches([], "billing_dispute_procedure.md")


def test_prohibited_claim_detection() -> None:
    assert contains_prohibited_claim(
        "We cannot guarantee a refund today.",
        ["guarantee a refund"],
    )
    assert not contains_prohibited_claim("We will review the charge.", ["approved"])


def test_no_knowledge_procedural_invention_detection() -> None:
    case = _case(expected_source_name=None)

    assert no_knowledge_response_is_safe(case, "We will route your question.")
    assert not no_knowledge_response_is_safe(
        case,
        "Please use the account recovery workflow.",
    )
    assert not no_knowledge_response_is_safe(
        case,
        "Escalate to billing operations for this unrelated question.",
    )


def test_retrieval_diagnostics_do_not_include_content() -> None:
    case = _case(expected_source_name=None)
    passages = [
        RetrievedPassage(
            content="Sensitive document content",
            source_name="account_access_procedure.md",
            source_path="sample_data/knowledge/account_access_procedure.md",
            relevance_score=0.75,
        )
    ]

    diagnostics = retrieval_diagnostics(case, passages)

    assert diagnostics == {
        "top_score": 0.75,
        "retrieved_count": 1,
        "expected_no_result": True,
        "actual_no_result": False,
    }


def test_metric_calculation() -> None:
    results = [
        {
            "schema_valid": True,
            "latency_ms": 10.0,
            "expected": {"source_name": "account_access_procedure.md"},
            "checks": {
                "category_correct": True,
                "priority_correct": True,
                "escalation_correct": True,
                "retrieval_hit": True,
                "source_top1_correct": True,
                "no_result_correct": True,
                "prohibited_claims_absent": True,
                "overall_passed": True,
            },
        },
        {
            "schema_valid": False,
            "latency_ms": 30.0,
            "expected": {"source_name": None},
            "checks": {
                "category_correct": False,
                "priority_correct": True,
                "escalation_correct": False,
                "retrieval_hit": False,
                "source_top1_correct": False,
                "no_result_correct": True,
                "prohibited_claims_absent": False,
                "overall_passed": False,
            },
        },
    ]

    metrics = calculate_metrics(results)

    assert metrics["category_accuracy"] == 0.5
    assert metrics["priority_accuracy"] == 1.0
    assert metrics["schema_validity_rate"] == 0.5
    assert metrics["expected_source_top1_accuracy"] == 1.0
    assert metrics["no_result_correctness"] == 1.0
    assert metrics["mean_latency_ms"] == 20.0


def test_groundedness_checks_include_expected_fields() -> None:
    case = _case(expected_source_name="account_access_procedure.md")
    response = TicketAnalysisResponse(
        ticket_id=case.case_id,
        summary="Customer cannot access account.",
        category="account_access",
        priority="high",
        sentiment="neutral",
        requires_escalation=False,
        escalation_reason=None,
        suggested_response="Use secure account recovery steps.",
        confidence=0.8,
    )
    passages = [
        RetrievedPassage(
            content="Account recovery procedure",
            source_name="account_access_procedure.md",
            source_path="sample_data/knowledge/account_access_procedure.md",
            relevance_score=1.0,
        )
    ]

    checks = evaluate_groundedness(case, response, passages)

    assert checks["category_correct"]
    assert checks["priority_correct"]
    assert checks["retrieval_hit"]
    assert checks["source_top1_correct"]
    assert checks["overall_passed"]


def test_report_generation_includes_metrics_and_failed_cases() -> None:
    report = render_markdown_report(
        {
            "timestamp": "2026-07-16T00:00:00+00:00",
            "run_configuration": {
                "provider": "mock",
                "knowledge_provider": "local",
                "dataset": "evaluation/data/support_cases.jsonl",
                "gemini_judge_enabled": False,
            },
            "metrics": {"category_accuracy": 1.0},
            "failed_cases": [
                {
                    "case_id": "EVAL-001",
                    "checks": {"category_correct": False, "overall_passed": False},
                    "latency_ms": 12.0,
                }
            ],
            "cases": [{"case_id": "EVAL-001", "latency_ms": 12.0}],
        }
    )

    assert "# Evaluation Summary" in report
    assert "`category_accuracy`" in report
    assert "`EVAL-001`" in report


def test_threshold_pass_fail_behavior() -> None:
    passing = evaluate_thresholds(
        {"category_accuracy": 0.9},
        {"category_accuracy": 0.8},
    )
    failing = evaluate_thresholds(
        {"category_accuracy": 0.7},
        {"category_accuracy": 0.8},
    )

    assert passing["passed"]
    assert not failing["passed"]
    assert not failing["metrics"]["category_accuracy"]["passed"]


def _case(expected_source_name: str | None) -> EvaluationCase:
    return EvaluationCase(
        case_id="EVAL-CASE",
        subject="Cannot access account",
        description="Cannot access account after reset.",
        channel="email",
        expected_category="account_access",
        expected_priority="high",
        expected_escalation=False,
        expected_source_name=expected_source_name,
        prohibited_claims=["share your password"],
        notes="synthetic",
    )
