from typing import Any

import faiss
import numpy as np
import requests

from pathlib import Path


class OllamaEmbeddingProvider:
    """使用本地Ollama将文本转换成向量。"""

    def __init__(
        self,
        model: str = "bge-m3",
        base_url: str = "http://localhost:11434",
    ) -> None:
        """保存Embedding模型和Ollama地址。"""
        self.model = model
        self.base_url = base_url

    def embed_texts(
        self,
        texts: list[str],
    ) -> np.ndarray:
        """将一批文本转换并归一化为向量。"""
        if not texts:
            raise ValueError("待转换文本不能为空")

        response = requests.post(
            f"{self.base_url}/api/embed",
            json={
                "model": self.model,
                "input": texts,
            },
            timeout=300,
        )

        response.raise_for_status()

        vectors = np.asarray(
            response.json()["embeddings"],
            dtype=np.float32,
        )

        faiss.normalize_L2(vectors)

        return vectors


class FAISSRetriever:
    """使用FAISS和余弦相似度检索知识片段。"""

    def __init__(
        self,
        chunks: list[dict[str, Any]],
        provider: OllamaEmbeddingProvider,
        index_path: Path | None = None,
    ) -> None:
        """将所有知识片段转换成向量并建立FAISS索引。"""
        if not chunks:
            raise ValueError("知识片段不能为空")

        self.chunks = chunks
        self.provider = provider

        if (
            index_path is not None
            and index_path.exists()
        ):
            self.index = faiss.read_index(
                str(index_path)
            )

            if self.index.ntotal != len(chunks):
                raise ValueError(
                    "FAISS索引数量与知识片段数量不一致"
                )

            return

        contents = [
            chunk["content"]
            for chunk in chunks
        ]

        vectors = provider.embed_texts(contents)

        self.index = faiss.IndexFlatIP(
            vectors.shape[1]
        )

        self.index.add(vectors)

        if index_path is not None:
            index_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            faiss.write_index(
                self.index,
                str(index_path),
            )

    def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """返回余弦相似度最高的Top-K知识片段。"""
        query_vector = self.provider.embed_texts(
            [query]
        )

        scores, indices = self.index.search(
            query_vector,
            min(top_k, len(self.chunks)),
        )

        results = []

        for score, index in zip(
            scores[0],
            indices[0],
        ):
            if index < 0:
                continue

            results.append(
                {
                    **self.chunks[index],
                    "vector_score": float(score),
                }
            )

        return results