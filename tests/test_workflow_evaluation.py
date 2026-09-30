"""工作流评测本身的回归测试。"""

from pathlib import Path

from vehicle_valuation.workflow_evaluation import (
    evaluate_document_intake,
    evaluate_market_agent,
    load_rag_baseline,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_document_intake_benchmark_routes_all_scenarios() -> None:
    result = evaluate_document_intake()

    assert result["scenario_count"] == 8
    assert result["auto_correction_success_rate"] == 1.0
    assert result["manual_routing_accuracy"] == 1.0
    assert result["auto_resolvable_critical_field_accuracy"] == 1.0


def test_market_agent_benchmark_enforces_60_point_floor() -> None:
    result = evaluate_market_agent()

    assert result["scenario_count"] == 5
    assert result["solvable_search_success_rate"] == 1.0
    assert result["automatic_top3_ready_rate"] == 1.0
    assert result["below_similarity_floor_block_rate"] == 1.0


def test_rag_baseline_is_loaded_from_independent_test_results() -> None:
    result = load_rag_baseline(PROJECT_ROOT)

    assert result["tuning_question_count"] == 10
    assert result["test_question_count"] == 5
    assert {item["retriever"] for item in result["test_results"]} == {
        "bm25",
        "faiss",
        "weighted_hybrid_rrf",
    }
