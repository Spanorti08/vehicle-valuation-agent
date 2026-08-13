from typing import Any


def format_rag_evidence(
    results: list[dict[str, Any]],
) -> str:
    """将BM25检索结果整理成LLM容易阅读的证据文本。"""
    evidence_blocks = []

    for result in results:
        evidence_blocks.append(
            "\n".join(
                [
                    f"片段编号：{result['chunk_id']}",
                    f"资料名称：{result['title']}",
                    f"来源：{result['source_url']}",
                    f"内容：{result['content']}",
                ]
            )
        )

    return "\n\n".join(evidence_blocks)


def build_rag_prompt(
    task: str,
    results: list[dict[str, Any]],
) -> str:
    """将写作任务和检索证据组合成RAG Prompt。"""
    evidence = format_rag_evidence(results)

    return f"""
你是资产评估报告起草助手。

写作任务：
{task}

要求：
1. 只能依据下方检索证据写作。
2. 不得编造法规、准则或者业务事实。
3. 每个主要结论后标注对应的片段编号，例如：
   [DOC-002-CHUNK-006]
4. 如果证据不足，明确写“现有资料不足”。
5. 使用正式、简洁的中文报告语言。

检索证据：
{evidence}

请完成写作任务。
""".strip()