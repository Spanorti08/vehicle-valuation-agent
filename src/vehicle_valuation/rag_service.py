from pathlib import Path
from typing import Any, Literal

from vehicle_valuation.hybrid_retriever import (
    HybridRetriever,
)
from vehicle_valuation.model import (
    GroundedReportSection,
)
from vehicle_valuation.rag_generation import (
    generate_grounded_section,
)
from vehicle_valuation.rag_retriever import (
    BM25Retriever,
    load_chunks,
)
from vehicle_valuation.vector_retriever import (
    FAISSRetriever,
    OllamaEmbeddingProvider,
)


class VehicleValuationRAG:
    """统一管理车辆评估知识库检索和内容生成。"""

    def __init__(
        self,
        chunks_path: Path,
        index_path: Path,
        retrieval_strategy: Literal[
            "faiss",
            "weighted_hybrid",
        ] = "faiss",
    ) -> None:
        """加载知识库，并保存经过评估的检索策略。"""
        if retrieval_strategy not in {
            "faiss",
            "weighted_hybrid",
        }:
            raise ValueError(
                "retrieval_strategy必须是faiss或weighted_hybrid"
            )

        self.retrieval_strategy = retrieval_strategy
        self.chunks = load_chunks(chunks_path)

        self.bm25_retriever = BM25Retriever(
            self.chunks
        )

        self.vector_retriever = FAISSRetriever(
            self.chunks,
            OllamaEmbeddingProvider(),
            index_path=index_path,
        )

        self.hybrid_retriever = HybridRetriever(
            self.bm25_retriever,
            self.vector_retriever,
        )

    def retrieve(
        self,
        query: str,
        allowed_document_types: set[str],
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """使用选定策略返回经过文档类型过滤的准则证据。"""
        if self.retrieval_strategy == "weighted_hybrid":
            return self.hybrid_retriever.search(
                query,
                top_k=top_k,
                candidate_k=20,
                bm25_weight=0.75,
                vector_weight=1.0,
                allowed_document_types=(
                    allowed_document_types
                ),
            )

        vector_results = self.vector_retriever.search(
            query,
            top_k=20,
        )

        filtered_results = [
            result
            for result in vector_results
            if result["document_type"]
            in allowed_document_types
        ]

        return filtered_results[:top_k]

    def generate_section(
        self,
        query: str,
        task: str,
        allowed_document_types: set[str],
    ) -> tuple[
        GroundedReportSection,
        list[dict[str, Any]],
    ]:
        """检索准则并生成带引用的报告章节。"""
        evidence = self.retrieve(
            query,
            allowed_document_types,
        )

        section = generate_grounded_section(
            task,
            evidence,
        )

        return section, evidence
