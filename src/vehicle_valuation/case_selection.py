"""高质量市场案例的确定性自动采用策略。"""

from __future__ import annotations

from decimal import Decimal
from statistics import median

from pydantic import BaseModel, Field

from vehicle_valuation.market_quality import MarketCaseQuality
from vehicle_valuation.model import MarketListing, MarketListingDetail


class AutomaticCaseSelection(BaseModel):
    approved: bool
    selected_urls: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


def evaluate_automatic_case_selection(
    listings: list[MarketListing],
    assessments: list[MarketCaseQuality],
    details: list[MarketListingDetail],
    screenshots: dict[str, tuple[bytes, bytes]],
    target_count: int = 3,
    minimum_score: int = 85,
    maximum_price_deviation: Decimal = Decimal("0.35"),
) -> AutomaticCaseSelection:
    """只有质量、证据、唯一性和价格分布均安全时自动采用 Top N。"""

    quality_by_url = {
        str(item.source_url): item
        for item in assessments
    }
    detail_urls = {str(item.source_url) for item in details}
    eligible = [
        item
        for item in listings
        if (
            (quality := quality_by_url.get(str(item.source_url)))
            and quality.qualified
            and quality.total_score >= minimum_score
        )
    ]
    eligible.sort(
        key=lambda item: quality_by_url[
            str(item.source_url)
        ].total_score,
        reverse=True,
    )
    reasons: list[str] = []
    if len(eligible) < target_count:
        reasons.append(
            f"达到{minimum_score}分的完整案例不足{target_count}个"
        )
        return AutomaticCaseSelection(approved=False, reasons=reasons)

    selected = eligible[:target_count]
    urls = [str(item.source_url) for item in selected]
    if len(urls) != len(set(urls)):
        reasons.append("候选案例URL重复")

    for listing in selected:
        url = str(listing.source_url)
        quality = quality_by_url[url]
        if quality.risk_warnings:
            reasons.append(
                f"{url}存在风险：{'；'.join(quality.risk_warnings)}"
            )
        if url not in detail_urls:
            reasons.append(f"{url}缺少详情字段")
        images = screenshots.get(url)
        if images is None or not all(images):
            reasons.append(f"{url}缺少同次读取截图")

    prices = [item.price_cny for item in selected]
    middle = Decimal(str(median(float(price) for price in prices)))
    if middle <= 0:
        reasons.append("案例价格中位数无效")
    else:
        for listing in selected:
            deviation = abs(listing.price_cny - middle) / middle
            if deviation > maximum_price_deviation:
                reasons.append(
                    f"{listing.source_url}价格偏离中位数{deviation:.0%}"
                )

    return AutomaticCaseSelection(
        approved=not reasons,
        selected_urls=(urls if not reasons else []),
        reasons=reasons,
    )
