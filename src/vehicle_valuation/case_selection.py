"""高质量市场案例的确定性自动采用策略。"""

from __future__ import annotations

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
    minimum_similarity_score: int = 60,
) -> AutomaticCaseSelection:
    """完整案例达到最低相似度且数量足够时自动采用 Top N。"""

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
            and quality.similarity_score >= minimum_similarity_score
            and str(item.source_url) in detail_urls
            and (
                (images := screenshots.get(str(item.source_url)))
                is not None
                and all(images)
            )
        )
    ]
    eligible.sort(
        key=lambda item: (
            quality_by_url[str(item.source_url)].similarity_score,
            quality_by_url[str(item.source_url)].total_score,
        ),
        reverse=True,
    )
    unique_eligible: list[MarketListing] = []
    seen_urls: set[str] = set()
    for item in eligible:
        url = str(item.source_url)
        if url not in seen_urls:
            unique_eligible.append(item)
            seen_urls.add(url)

    reasons: list[str] = []
    if len(unique_eligible) < target_count:
        reasons.append(
            f"达到最低相似度{minimum_similarity_score}分的完整案例"
            f"不足{target_count}个"
        )
        return AutomaticCaseSelection(approved=False, reasons=reasons)

    selected = unique_eligible[:target_count]
    urls = [str(item.source_url) for item in selected]

    return AutomaticCaseSelection(
        approved=True,
        selected_urls=urls,
        reasons=[],
    )
