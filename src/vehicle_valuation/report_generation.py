import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from vehicle_valuation.llm_provider import OllamaProvider
from vehicle_valuation.model import (
    MarketListing,
    ValuationRequest,
    VehicleValuationReportDraft,
)
from vehicle_valuation.rag_prompt import format_rag_evidence


def load_report_template(
    template_path: Path,
) -> str:
    """读取车辆评估报告Markdown模板。"""

    if not template_path.exists():
        raise FileNotFoundError(
            f"找不到报告模板：{template_path}"
        )

    return template_path.read_text(
        encoding="utf-8"
    )


def build_full_report_prompt(
    request: ValuationRequest,
    listings: list[MarketListing],
    final_value: Decimal,
    evidence: list[dict[str, Any]],
    template_text: str,
) -> str:
    """把业务数据、计算结果和RAG证据整理成报告生成Prompt。"""

    request_text = request.model_dump_json(indent=2)

    listings_text = json.dumps(
        [
            listing.model_dump(mode="json")
            for listing in listings
        ],
        ensure_ascii=False,
        indent=2,
    )

    evidence_text = format_rag_evidence(evidence)

    return f"""
你是车辆资产评估报告初稿助手。

请根据业务数据、Python计算结果和检索到的公开准则证据，
生成完整的车辆评估报告初稿。

必须遵循以下报告模板的章节顺序和内容要求：
{template_text}


重要要求：
1. 不得编造未提供的业务信息。
2. 缺失信息写“待补充”，并加入missing_information。
3. 准则相关内容只能依据RAG证据。
4. 引用准则时标注片段编号，例如[DOC-002-CHUNK-005]。
5. cited_chunk_ids只能填写实际使用的片段编号。
6. 市场案例价格属于公开挂牌价，不能写成成交价。
7. 最终评估值由Python计算，必须使用{final_value}元，
   不得重新计算或者修改。
8. 行驶证所有人不能直接认定为委托人。
9. 明确说明这是供专业人员复核的初稿，不是正式签字报告。
10. 使用正式、简洁的中文。

待评车辆资料：
{request_text}

市场案例：
{listings_text}

Python计算的最终评估值：
{final_value}元

RAG检索证据：
{evidence_text}
""".strip()


def generate_full_report_draft(
    request: ValuationRequest,
    listings: list[MarketListing],
    final_value: Decimal,
    evidence: list[dict[str, Any]],
    template_path: Path,
    provider: OllamaProvider | None = None,
) -> VehicleValuationReportDraft:
    """调用LLM生成完整报告初稿，并检查引用是否真实存在。"""

    template_text = load_report_template(
        template_path
    )

    if provider is None:
        provider = OllamaProvider()

    prompt = build_full_report_prompt(
        request=request,
        listings=listings,
        final_value=final_value,
        evidence=evidence,
        template_text=template_text,
    )

    draft = provider.generate(
        prompt,
        VehicleValuationReportDraft,
    )

    allowed_chunk_ids = {
        item["chunk_id"]
        for item in evidence
    }

    invalid_chunk_ids = (
        set(draft.cited_chunk_ids)
        - allowed_chunk_ids
    )

    if invalid_chunk_ids:
        raise ValueError(
            f"报告引用了不存在的证据：{invalid_chunk_ids}"
        )

    return draft