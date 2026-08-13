from decimal import Decimal
from typing import Any

from vehicle_valuation.model import (
    GroundedReportSection,
    MarketListing,
    ValuationRequest,
    VehicleValuationReportDraft,
)


def format_market_cases(
    listings: list[MarketListing],
) -> str:
    """把已确认的市场案例整理成报告文字。"""

    listing_urls = [
        str(listing.source_url)
        for listing in listings
    ]

    if len(listing_urls) < 3:
        raise ValueError("报告至少需要3个市场案例")

    if len(listing_urls) != len(set(listing_urls)):
        raise ValueError("报告市场案例中存在重复车源")

    case_lines = []

    for number, listing in enumerate(
        listings,
        start=1,
    ):
        case_lines.append(
            (
                f"实例{number}：{listing.vehicle_model}，"
                f"{listing.registration_year}年上牌，"
                f"里程{listing.mileage_km:,}公里，"
                f"公开挂牌价{listing.price_cny:,.0f}元，"
                f"车源地{listing.city}，"
                f"来源为{listing.source_name}公开页面，"
                "网页链接及截图详见案例附件。"
            )
        )

    return "\n".join(case_lines)


def format_valuation_basis(
    evidence: list[dict[str, Any]],
) -> str:
    """根据RAG证据生成去重后的评估依据清单。"""

    sources = {}

    for item in evidence:
        sources[item["title"]] = item["source_url"]

    return "\n".join(
        f"- {title}：{source_url}"
        for title, source_url in sources.items()
    )


def collect_cited_chunk_ids(
    sections: dict[str, GroundedReportSection],
) -> list[str]:
    """汇总所有章节引用并保持编号不重复。"""

    cited_chunk_ids = []

    for section in sections.values():
        for chunk_id in section.cited_chunk_ids:
            if chunk_id not in cited_chunk_ids:
                cited_chunk_ids.append(chunk_id)

    return cited_chunk_ids


def build_report_draft(
    request: ValuationRequest,
    listings: list[MarketListing],
    final_value: Decimal,
    evidence: list[dict[str, Any]],
    sections: dict[str, GroundedReportSection],
) -> VehicleValuationReportDraft:
    """把业务数据和RAG章节合并成完整报告初稿。"""

    vehicle = request.subject_vehicle
    license_data = request.driving_license
    inspection = request.inspection

    market_cases = format_market_cases(listings)
    valuation_basis = format_valuation_basis(evidence)

    missing_information = [
        "委托人信息",
        "报告使用人信息",
        "正式评估目的",
    ]

    return VehicleValuationReportDraft(
        report_title=(
            f"{vehicle.vehicle_name}车辆评估报告初稿"
        ),
        declaration=sections["declaration"].content,
        summary=(
            f"评估对象为{vehicle.vehicle_name}，"
            f"车辆牌号为{vehicle.plate_number}，"
            f"评估基准日为"
            f"{request.valuation_date:%Y年%m月%d日}，"
            f"采用市场法评估，"
            f"评估建议值为{final_value}元。"
        ),
        client_and_users=(
            "委托人及报告使用人信息待补充。"
            f"行驶证登记所有人为"
            f"{license_data.owner_name}，"
            "但不能据此直接认定其为委托人。"
        ),
        valuation_purpose="正式评估目的待补充。",
        object_and_scope=(
            f"评估对象为{vehicle.vehicle_name}，"
            f"资产编号{vehicle.asset_id}，"
            f"车辆牌号{vehicle.plate_number}，"
            f"行驶证品牌型号"
            f"{license_data.vehicle_model}，"
            f"车辆识别代号{license_data.vin}，"
            f"现场里程{inspection.actual_mileage_km:,}公里。"
        ),
        value_type=sections["value_type"].content,
        valuation_date=(
            f"评估基准日为"
            f"{request.valuation_date:%Y年%m月%d日}。"
        ),
        valuation_basis=valuation_basis,
        valuation_method=(
            f"{sections['valuation_method'].content}\n\n"
            f"本次选取的市场案例：\n{market_cases}"
        ),
        valuation_process=(
            sections["valuation_process"].content
        ),
        assumptions=(
            "本初稿以用户上传并确认的车辆资料、"
            "行驶证识别结果、现场核查信息及"
            "公开市场案例为基础，相关信息仍需"
            "资产评估专业人员复核。"
        ),
        conclusion=(
            f"经市场法测算，本次车辆评估"
            f"建议值为人民币{final_value}元。"
            "该结果为报告初稿数据，不构成正式签字结论。"
        ),
        special_matters=(
            "本报告为自动生成的评估初稿，尚需资产评估"
            "专业人员复核。市场案例价格来自公开二手车"
            "页面，属于挂牌信息，未经电话询价或成交确认；"
            "公开页面通常只披露综合车况，未分别披露外观、"
            "内饰及硬件的完整检测细节。行驶证OCR结果、"
            "AI参数建议和资料一致性检查均可能存在误差。"
            "委托人信息、经济行为依据、评估机构及签字人员"
            "等正式报告要素仍需补充确认。"
        ),
        usage_restrictions=(
            sections["usage_restrictions"].content
        ),
        cited_chunk_ids=collect_cited_chunk_ids(
            sections
        ),
        missing_information=missing_information,
    )
