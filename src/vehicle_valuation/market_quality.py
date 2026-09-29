from __future__ import annotations

from decimal import Decimal
from difflib import SequenceMatcher
from statistics import median

from pydantic import BaseModel, Field, HttpUrl, model_validator

from vehicle_valuation.market_scraper import (
    calculate_listing_similarity,
    normalize_market_model,
)
from vehicle_valuation.model import MarketListing


class MarketCaseQuality(BaseModel):
    """保存一个市场案例的质量分、风险和拒绝原因。"""

    source_url: HttpUrl
    model_match_score: int = Field(ge=0, le=30)
    year_match_score: int = Field(ge=0, le=15)
    mileage_match_score: int = Field(ge=0, le=15)
    source_completeness_score: int = Field(ge=0, le=15)
    page_validity_score: int = Field(ge=0, le=10)
    price_risk_score: int = Field(ge=0, le=10)
    region_score: int = Field(ge=0, le=5)
    similarity_score: int = Field(default=100, ge=0, le=100)
    total_score: int = Field(default=0, ge=0, le=100)
    qualified: bool = False
    risk_warnings: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def calculate_total(self) -> "MarketCaseQuality":
        self.total_score = sum(
            (
                self.model_match_score,
                self.year_match_score,
                self.mileage_match_score,
                self.source_completeness_score,
                self.page_validity_score,
                self.price_risk_score,
                self.region_score,
            )
        )
        return self


class RejectedMarketCase(BaseModel):
    """记录被拒绝案例及其确定性原因。"""

    source_url: HttpUrl
    vehicle_model: str
    reasons: list[str] = Field(min_length=1)


def _model_match_score(
    listing_model: str,
    market_keyword: str,
) -> int:
    normalized_model = normalize_market_model(listing_model)
    normalized_keyword = normalize_market_model(market_keyword)

    if not normalized_model or not normalized_keyword:
        return 0
    if (
        normalized_keyword in normalized_model
        or normalized_model in normalized_keyword
    ):
        return 30

    ratio = SequenceMatcher(
        None,
        normalized_keyword,
        normalized_model,
    ).ratio()
    if ratio >= 0.75:
        return 26
    if ratio >= 0.55:
        return 20
    if ratio >= 0.35:
        return 12
    return 0


def _price_risk_score(
    listing: MarketListing,
    median_price: Decimal,
) -> tuple[int, list[str], list[str]]:
    warnings: list[str] = []
    rejections: list[str] = []
    price = listing.price_cny

    if price < Decimal("5000") or price > Decimal("5000000"):
        rejections.append("挂牌价格单位或数值明显异常")
        return 0, warnings, rejections

    suspicious_terms = ("事故", "泡水", "火烧", "新车")
    if any(term in listing.vehicle_model for term in suspicious_terms):
        warnings.append("车型文字可能表示事故车、新车或特殊车况")

    if median_price <= 0:
        return 5, warnings, rejections

    ratio = price / median_price
    if Decimal("0.5") <= ratio <= Decimal("1.8"):
        return 10, warnings, rejections
    if Decimal("0.3") <= ratio <= Decimal("2.5"):
        warnings.append("挂牌价格偏离当前候选案例中位数")
        return 5, warnings, rejections

    warnings.append("挂牌价格明显偏离当前候选案例中位数")
    return 0, warnings, rejections


def score_market_cases(
    listings: list[MarketListing],
    market_keyword: str,
    target_year: int,
    target_mileage_km: int,
    preferred_cities: set[str],
    page_valid_urls: set[str],
    year_tolerance: int,
    mileage_tolerance_km: int,
    minimum_quality_score: int,
    minimum_similarity_score: int = 60,
) -> list[MarketCaseQuality]:
    """按流程图中的七类因素确定性评价市场案例。"""

    if not listings:
        return []

    median_price = Decimal(
        str(median(float(item.price_cny) for item in listings))
    )
    seen_signatures: set[tuple[object, ...]] = set()
    results: list[MarketCaseQuality] = []

    for listing in listings:
        rejection_reasons: list[str] = []
        risk_warnings: list[str] = []
        url = str(listing.source_url)
        similarity_score = round(
            calculate_listing_similarity(
                listing,
                target_year,
                target_mileage_km,
            )
            * 100
        )
        if similarity_score < minimum_similarity_score:
            rejection_reasons.append(
                f"年份与里程综合匹配分低于{minimum_similarity_score}分"
            )

        model_score = _model_match_score(
            listing.vehicle_model,
            market_keyword,
        )
        if model_score == 0:
            rejection_reasons.append("车型与目标车型明显不匹配")

        year_difference = abs(listing.registration_year - target_year)
        year_score = max(0, 15 - year_difference * 5)
        if year_difference > year_tolerance:
            rejection_reasons.append(
                f"上牌年份超出允许范围±{year_tolerance}年"
            )

        mileage_difference = abs(
            listing.mileage_km - target_mileage_km
        )
        if mileage_tolerance_km <= 0:
            mileage_score = 0
        else:
            mileage_score = max(
                0,
                round(
                    15
                    * (
                        1
                        - mileage_difference
                        / mileage_tolerance_km
                    )
                ),
            )
        if mileage_difference > mileage_tolerance_km:
            rejection_reasons.append(
                "行驶里程超出当前允许差值"
            )

        required_values = (
            listing.vehicle_model,
            listing.registration_year,
            listing.mileage_km,
            listing.city,
            listing.price_cny,
            url,
        )
        completeness_score = round(
            15
            * sum(value not in (None, "") for value in required_values)
            / len(required_values)
        )

        page_score = 10 if url in page_valid_urls else 0
        if page_score == 0:
            rejection_reasons.append(
                "详情页、价格或网页截图未能完整保存"
            )

        signature = (
            normalize_market_model(listing.vehicle_model),
            listing.registration_year,
            listing.mileage_km,
            listing.price_cny,
            listing.city,
        )
        if signature in seen_signatures:
            risk_warnings.append("疑似同一车辆重复发布，需人工复核")
        seen_signatures.add(signature)

        price_score, price_warnings, price_rejections = (
            _price_risk_score(listing, median_price)
        )
        risk_warnings.extend(price_warnings)
        rejection_reasons.extend(price_rejections)

        region_score = 5 if listing.city in preferred_cities else 3
        if listing.city not in preferred_cities:
            risk_warnings.append("案例不在初始目标城市")

        quality = MarketCaseQuality(
            source_url=listing.source_url,
            model_match_score=model_score,
            year_match_score=year_score,
            mileage_match_score=mileage_score,
            source_completeness_score=completeness_score,
            page_validity_score=page_score,
            price_risk_score=price_score,
            region_score=region_score,
            similarity_score=similarity_score,
            risk_warnings=risk_warnings,
            rejection_reasons=list(dict.fromkeys(rejection_reasons)),
        )
        quality.qualified = (
            not quality.rejection_reasons
            and quality.total_score >= minimum_quality_score
        )
        if (
            not quality.qualified
            and not quality.rejection_reasons
        ):
            quality.rejection_reasons.append(
                f"综合质量分低于{minimum_quality_score}分"
            )
        results.append(quality)

    return results
