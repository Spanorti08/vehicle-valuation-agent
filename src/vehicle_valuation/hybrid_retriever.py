from typing import Any

from vehicle_valuation.rag_retriever import (
    BM25Retriever,
)
from vehicle_valuation.vector_retriever import (
    FAISSRetriever,
)


class HybridRetriever:
    """使用RRF融合BM25和FAISS检索结果。"""

    def __init__(
        self,
        bm25_retriever: BM25Retriever,
        vector_retriever: FAISSRetriever,
    ) -> None:
        """保存关键词检索器和向量检索器。"""
        self.bm25_retriever = bm25_retriever
        self.vector_retriever = vector_retriever

    def search(
        self,
        query: str,
        top_k: int = 5,
        candidate_k: int = 10,
        rrf_k: int = 60,
        bm25_weight: float = 1.0,
        vector_weight: float = 1.0,
        allowed_document_types: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """通过加权RRF分数返回混合检索Top-K结果。"""

        if bm25_weight < 0 or vector_weight < 0:
            raise ValueError("检索权重不能小于0")

        if bm25_weight == 0 and vector_weight == 0:
            raise ValueError("至少一个检索权重必须大于0")

        bm25_results = self.bm25_retriever.search(
            query,
            top_k=candidate_k,
        )

        vector_results = self.vector_retriever.search(
            query,
            top_k=candidate_k,
        )

        if allowed_document_types is not None:
            bm25_results = [
                result
                for result in bm25_results
                if result["document_type"]
                in allowed_document_types
            ]

            vector_results = [
                result
                for result in vector_results
                if result["document_type"]
                in allowed_document_types
            ]

        return self.fuse_results(
            bm25_results,
            vector_results,
            top_k=top_k,
            rrf_k=rrf_k,
            bm25_weight=bm25_weight,
            vector_weight=vector_weight,
        )

    @staticmethod
    def fuse_results(
        bm25_results: list[dict[str, Any]],
        vector_results: list[dict[str, Any]],
        top_k: int,
        rrf_k: int = 60,
        bm25_weight: float = 1.0,
        vector_weight: float = 1.0,
    ) -> list[dict[str, Any]]:
        """融合已经检索到的BM25和FAISS候选结果。"""

        combined = {}

        retrieval_results = [
            ("bm25", bm25_results, bm25_weight),
            ("vector", vector_results, vector_weight),
        ]

        for retrieval_name, results, weight in retrieval_results:
            for rank, result in enumerate(
                results,
                start=1,
            ):
                chunk_id = result["chunk_id"]

                if chunk_id not in combined:
                    combined[chunk_id] = {
                        **result,
                        "hybrid_score": 0.0,
                        "bm25_rank": None,
                        "vector_rank": None,
                    }

                combined[chunk_id].update(result)

                combined[chunk_id][
                    "hybrid_score"
                ] += weight / (rrf_k + rank)

                combined[chunk_id][
                    f"{retrieval_name}_rank"
                ] = rank

        ranked_results = sorted(
            combined.values(),
            key=lambda result: result["hybrid_score"],
            reverse=True,
        )

        return ranked_results[:top_k]
