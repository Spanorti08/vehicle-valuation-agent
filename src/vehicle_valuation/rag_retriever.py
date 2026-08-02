import json
from pathlib import Path
from typing import Any

import jieba
from rank_bm25 import BM25Okapi


def tokenize_chinese(text: str) -> list[str]:
    """使用jieba将中文文本拆成BM25可以处理的词语。"""
    return [
        token.strip()
        for token in jieba.cut(text)
        if token.strip()
    ]


def load_chunks(path: Path) -> list[dict[str, Any]]:
    """从JSONL文件逐行读取知识库片段。"""
    chunks = []

    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                chunks.append(json.loads(line))

    return chunks


class BM25Retriever:
    """根据关键词相关性检索准则条款。"""

    def __init__(
        self,
        chunks: list[dict[str, Any]],
    ) -> None:
        """使用知识库片段创建BM25索引。"""
        self.chunks = chunks

        tokenized_corpus = [
            tokenize_chinese(chunk["content"])
            for chunk in chunks
        ]

        self.index = BM25Okapi(tokenized_corpus)

    def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """返回与问题最相关的Top-K知识片段。"""
        query_tokens = tokenize_chinese(query)
        scores = self.index.get_scores(query_tokens)

        ranked_indices = sorted(
            range(len(scores)),
            key=lambda index: scores[index],
            reverse=True,
        )

        results = []

        for index in ranked_indices:
            if scores[index] <= 0:
                continue

            results.append(
                {
                    **self.chunks[index],
                    "score": float(scores[index]),
                }
            )

            if len(results) >= top_k:
                break

        return results