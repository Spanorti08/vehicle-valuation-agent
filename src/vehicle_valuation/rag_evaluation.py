import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


SearchFunction = Callable[
    [str, set[str], int],
    list[dict[str, Any]],
]


def load_evaluation_questions(
    path: Path,
) -> list[dict[str, Any]]:
    """读取并检查RAG评估问题。"""

    questions = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(questions, list) or not questions:
        raise ValueError("RAG评估问题不能为空")

    required_fields = {
        "question_id",
        "split",
        "question",
        "expected_chunk_ids",
        "allowed_document_types",
    }

    for question in questions:
        missing_fields = required_fields - question.keys()

        if missing_fields:
            raise ValueError(
                "评估问题缺少字段："
                f"{sorted(missing_fields)}"
            )

        if not question["expected_chunk_ids"]:
            raise ValueError(
                f"{question['question_id']}没有正确答案"
            )

        if question["split"] not in {"tuning", "test"}:
            raise ValueError(
                f"{question['question_id']}的split无效"
            )

    return questions


def calculate_question_metrics(
    returned_chunk_ids: list[str],
    expected_chunk_ids: list[str],
    top_k: int,
) -> dict[str, float | int | None]:
    """计算单个问题的Hit、Recall和倒数排名。"""

    top_results = returned_chunk_ids[:top_k]
    expected = set(expected_chunk_ids)
    relevant_ranks = [
        rank
        for rank, chunk_id in enumerate(
            top_results,
            start=1,
        )
        if chunk_id in expected
    ]
    retrieved_relevant_count = len(relevant_ranks)
    first_relevant_rank = (
        min(relevant_ranks)
        if relevant_ranks
        else None
    )

    return {
        "hit": int(first_relevant_rank is not None),
        "recall": (
            retrieved_relevant_count / len(expected)
        ),
        "reciprocal_rank": (
            1 / first_relevant_rank
            if first_relevant_rank is not None
            else 0.0
        ),
        "first_relevant_rank": first_relevant_rank,
    }


def evaluate_retriever(
    retriever_name: str,
    search: SearchFunction,
    questions: list[dict[str, Any]],
    top_k: int = 3,
) -> dict[str, Any]:
    """在同一组问题上评估一个检索器。"""

    question_results = []

    for question in questions:
        results = search(
            question["question"],
            set(question["allowed_document_types"]),
            top_k,
        )
        returned_chunk_ids = [
            result["chunk_id"]
            for result in results
        ]
        metrics = calculate_question_metrics(
            returned_chunk_ids,
            question["expected_chunk_ids"],
            top_k,
        )

        question_results.append(
            {
                "question_id": question["question_id"],
                "question": question["question"],
                "expected_chunk_ids": (
                    question["expected_chunk_ids"]
                ),
                "returned_chunk_ids": returned_chunk_ids,
                **metrics,
            }
        )

    question_count = len(question_results)

    return {
        "retriever": retriever_name,
        "question_count": question_count,
        f"hit_rate_at_{top_k}": sum(
            result["hit"]
            for result in question_results
        )
        / question_count,
        f"mean_recall_at_{top_k}": sum(
            result["recall"]
            for result in question_results
        )
        / question_count,
        f"mrr_at_{top_k}": sum(
            result["reciprocal_rank"]
            for result in question_results
        )
        / question_count,
        "questions": question_results,
    }


def write_evaluation_results(
    results: dict[str, Any],
    path: Path,
) -> None:
    """将RAG评估结果保存为JSON文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            results,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
