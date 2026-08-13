from vehicle_valuation.rag_evaluation import (
    calculate_question_metrics,
)
from vehicle_valuation.hybrid_retriever import (
    HybridRetriever,
)


def test_metrics_when_relevant_chunk_is_first() -> None:
    """正确片段排第一时Hit和MRR都应为1。"""

    metrics = calculate_question_metrics(
        ["CHUNK-A", "CHUNK-B", "CHUNK-C"],
        ["CHUNK-A"],
        top_k=3,
    )

    assert metrics["hit"] == 1
    assert metrics["recall"] == 1
    assert metrics["reciprocal_rank"] == 1
    assert metrics["first_relevant_rank"] == 1


def test_metrics_when_relevant_chunk_is_third() -> None:
    """正确片段排第三时倒数排名应为三分之一。"""

    metrics = calculate_question_metrics(
        ["CHUNK-A", "CHUNK-B", "CHUNK-C"],
        ["CHUNK-C"],
        top_k=3,
    )

    assert metrics["hit"] == 1
    assert metrics["reciprocal_rank"] == 1 / 3
    assert metrics["first_relevant_rank"] == 3


def test_metrics_when_no_relevant_chunk_is_returned() -> None:
    """前三条没有正确片段时所有命中指标应为0。"""

    metrics = calculate_question_metrics(
        ["CHUNK-A", "CHUNK-B", "CHUNK-C"],
        ["CHUNK-D"],
        top_k=3,
    )

    assert metrics["hit"] == 0
    assert metrics["recall"] == 0
    assert metrics["reciprocal_rank"] == 0
    assert metrics["first_relevant_rank"] is None


def test_weighted_rrf_can_favor_vector_result() -> None:
    """提高FAISS权重后，其第一名应成为融合第一名。"""

    bm25_results = [
        {"chunk_id": "BM25-FIRST"},
        {"chunk_id": "VECTOR-FIRST"},
    ]
    vector_results = [
        {"chunk_id": "VECTOR-FIRST"},
        {"chunk_id": "BM25-FIRST"},
    ]

    results = HybridRetriever.fuse_results(
        bm25_results,
        vector_results,
        top_k=2,
        bm25_weight=0.25,
        vector_weight=1.0,
    )

    assert results[0]["chunk_id"] == "VECTOR-FIRST"
