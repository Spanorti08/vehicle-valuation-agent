from typing import Any

from vehicle_valuation.llm_provider import OllamaProvider
from vehicle_valuation.model import GroundedReportSection
from vehicle_valuation.rag_prompt import build_rag_prompt


def generate_grounded_section(
    task: str,
    results: list[dict[str, Any]],
    provider: OllamaProvider | None = None,
) -> GroundedReportSection:
    """让LLM基于检索证据生成报告章节并校验引用。"""
    prompt = build_rag_prompt(task, results)

    prompt += """
    
输出要求：
- section_title：章节标题
- content：报告正文，正文中标注引用片段编号
- cited_chunk_ids：实际引用的片段编号列表
""".rstrip()

    llm = provider or OllamaProvider()

    response = llm.generate(
        prompt,
        GroundedReportSection,
    )

    allowed_ids = {
        result["chunk_id"]
        for result in results
    }

    invalid_ids = (
        set(response.cited_chunk_ids)
        - allowed_ids
    )

    if invalid_ids:
        raise ValueError(
            f"LLM引用了未检索到的片段：{invalid_ids}"
        )

    return response