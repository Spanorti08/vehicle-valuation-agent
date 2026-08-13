from pathlib import Path
from typing import Any

from vehicle_valuation.hybrid_retriever import (
    HybridRetriever,
)
from vehicle_valuation.rag_evaluation import (
    evaluate_retriever,
    load_evaluation_questions,
    write_evaluation_results,
)
from vehicle_valuation.rag_retriever import (
    BM25Retriever,
    load_chunks,
)
from vehicle_valuation.vector_retriever import (
    FAISSRetriever,
    OllamaEmbeddingProvider,
)


PROJECT_DIR = Path(__file__).parents[1]
CHUNKS_PATH = PROJECT_DIR / "data/rag/processed/chunks.jsonl"
INDEX_PATH = PROJECT_DIR / "data/rag/processed/faiss.index"
QUESTIONS_PATH = (
    PROJECT_DIR / "data/rag/evaluation_questions.json"
)
RESULTS_PATH = (
    PROJECT_DIR / "data/rag/evaluation_results.json"
)
TOP_K = 3
CANDIDATE_K = 20
WEIGHT_CANDIDATES = [
    (1.0, 1.0),
    (0.75, 1.0),
    (0.5, 1.0),
    (0.25, 1.0),
]


def filter_results(
    results: list[dict[str, Any]],
    allowed_document_types: set[str],
    top_k: int,
) -> list[dict[str, Any]]:
    """按生产环境的文档类型限制筛选候选结果。"""

    return [
        result
        for result in results
        if result["document_type"]
        in allowed_document_types
    ][:top_k]


def main() -> None:
    """在调参集选权重，并在保留测试集比较检索器。"""

    chunks = load_chunks(CHUNKS_PATH)
    questions = load_evaluation_questions(
        QUESTIONS_PATH
    )
    tuning_questions = [
        question
        for question in questions
        if question["split"] == "tuning"
    ]
    test_questions = [
        question
        for question in questions
        if question["split"] == "test"
    ]

    bm25 = BM25Retriever(chunks)
    vector = FAISSRetriever(
        chunks,
        OllamaEmbeddingProvider(),
        index_path=INDEX_PATH,
    )
    hybrid = HybridRetriever(bm25, vector)
    bm25_cache: dict[str, list[dict[str, Any]]] = {}
    vector_cache: dict[str, list[dict[str, Any]]] = {}

    def get_bm25_candidates(
        query: str,
    ) -> list[dict[str, Any]]:
        """缓存BM25候选结果，避免调权重时重复检索。"""

        if query not in bm25_cache:
            bm25_cache[query] = bm25.search(
                query,
                top_k=CANDIDATE_K,
            )

        return bm25_cache[query]

    def get_vector_candidates(
        query: str,
    ) -> list[dict[str, Any]]:
        """缓存FAISS候选结果，避免重复生成问题向量。"""

        if query not in vector_cache:
            vector_cache[query] = vector.search(
                query,
                top_k=CANDIDATE_K,
            )

        return vector_cache[query]

    def search_bm25(
        query: str,
        allowed_document_types: set[str],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """使用BM25检索并应用元数据过滤。"""

        return filter_results(
            get_bm25_candidates(query),
            allowed_document_types,
            top_k,
        )

    def search_vector(
        query: str,
        allowed_document_types: set[str],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """使用FAISS检索并应用元数据过滤。"""

        return filter_results(
            get_vector_candidates(query),
            allowed_document_types,
            top_k,
        )

    def build_hybrid_search(
        bm25_weight: float,
        vector_weight: float,
    ):
        """创建指定权重的加权RRF检索函数。"""

        def search_hybrid(
            query: str,
            allowed_document_types: set[str],
            top_k: int,
        ) -> list[dict[str, Any]]:
            """融合过滤后的BM25和FAISS候选结果。"""

            bm25_results = filter_results(
                get_bm25_candidates(query),
                allowed_document_types,
                CANDIDATE_K,
            )
            vector_results = filter_results(
                get_vector_candidates(query),
                allowed_document_types,
                CANDIDATE_K,
            )

            return hybrid.fuse_results(
                bm25_results,
                vector_results,
                top_k=top_k,
                bm25_weight=bm25_weight,
                vector_weight=vector_weight,
            )

        return search_hybrid

    tuning_results = []

    for bm25_weight, vector_weight in WEIGHT_CANDIDATES:
        result = evaluate_retriever(
            (
                "hybrid_rrf_"
                f"bm25_{bm25_weight}_"
                f"vector_{vector_weight}"
            ),
            build_hybrid_search(
                bm25_weight,
                vector_weight,
            ),
            tuning_questions,
            top_k=TOP_K,
        )
        result["bm25_weight"] = bm25_weight
        result["vector_weight"] = vector_weight
        tuning_results.append(result)

    selected_tuning_result = max(
        tuning_results,
        key=lambda result: (
            result[f"hit_rate_at_{TOP_K}"],
            result[f"mrr_at_{TOP_K}"],
            result[f"mean_recall_at_{TOP_K}"],
        ),
    )
    selected_bm25_weight = selected_tuning_result[
        "bm25_weight"
    ]
    selected_vector_weight = selected_tuning_result[
        "vector_weight"
    ]

    test_results = [
        evaluate_retriever(
            "bm25",
            search_bm25,
            test_questions,
            top_k=TOP_K,
        ),
        evaluate_retriever(
            "faiss",
            search_vector,
            test_questions,
            top_k=TOP_K,
        ),
        evaluate_retriever(
            "weighted_hybrid_rrf",
            build_hybrid_search(
                selected_bm25_weight,
                selected_vector_weight,
            ),
            test_questions,
            top_k=TOP_K,
        ),
    ]

    evaluations = {
        "top_k": TOP_K,
        "question_count": len(questions),
        "tuning_question_count": len(tuning_questions),
        "test_question_count": len(test_questions),
        "weight_candidates": tuning_results,
        "selected_weights": {
            "bm25_weight": selected_bm25_weight,
            "vector_weight": selected_vector_weight,
        },
        "test_results": test_results,
    }
    write_evaluation_results(
        evaluations,
        RESULTS_PATH,
    )

    print(
        f"评估问题数量：{len(questions)} "
        f"(调参={len(tuning_questions)}, "
        f"测试={len(test_questions)})"
    )
    print(
        "选中权重："
        f"BM25={selected_bm25_weight}, "
        f"FAISS={selected_vector_weight}"
    )

    for result in test_results:
        print(
            f"{result['retriever']}: "
            f"Hit@{TOP_K}="
            f"{result[f'hit_rate_at_{TOP_K}']:.1%}, "
            f"Recall@{TOP_K}="
            f"{result[f'mean_recall_at_{TOP_K}']:.1%}, "
            f"MRR@{TOP_K}="
            f"{result[f'mrr_at_{TOP_K}']:.3f}"
        )

    print(f"详细结果：{RESULTS_PATH}")


if __name__ == "__main__":
    main()
