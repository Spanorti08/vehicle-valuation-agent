from decimal import Decimal

from vehicle_valuation.case_selection import evaluate_automatic_case_selection
from vehicle_valuation.market_quality import MarketCaseQuality
from vehicle_valuation.model import MarketListing, MarketListingDetail


def _listing(index: int, price: str = "80000") -> MarketListing:
    return MarketListing(
        source_url=f"https://example.com/case-{index}",
        vehicle_model=f"测试车型{index}",
        registration_year=2018,
        mileage_km=80_000 + index,
        city="北京",
        price_cny=Decimal(price),
    )


def _quality(listing: MarketListing, score: int = 95) -> MarketCaseQuality:
    return MarketCaseQuality(
        source_url=listing.source_url,
        model_match_score=30,
        year_match_score=15,
        mileage_match_score=15,
        source_completeness_score=15,
        page_validity_score=10,
        price_risk_score=max(0, score - 90),
        region_score=5,
        qualified=True,
    )


def test_three_clean_high_quality_cases_are_auto_selected() -> None:
    listings = [_listing(index) for index in range(1, 4)]
    result = evaluate_automatic_case_selection(
        listings,
        [_quality(item) for item in listings],
        [MarketListingDetail(source_url=item.source_url) for item in listings],
        {
            str(item.source_url): (b"top", b"detail")
            for item in listings
        },
    )

    assert result.approved is True
    assert len(result.selected_urls) == 3


def test_risky_case_requires_human_selection() -> None:
    listings = [_listing(index) for index in range(1, 4)]
    qualities = [_quality(item) for item in listings]
    qualities[0].risk_warnings.append("疑似重复发布")

    result = evaluate_automatic_case_selection(
        listings,
        qualities,
        [MarketListingDetail(source_url=item.source_url) for item in listings],
        {
            str(item.source_url): (b"top", b"detail")
            for item in listings
        },
    )

    assert result.approved is False
    assert any("疑似重复发布" in reason for reason in result.reasons)


def test_price_outlier_requires_human_selection() -> None:
    listings = [_listing(1), _listing(2), _listing(3, "160000")]

    result = evaluate_automatic_case_selection(
        listings,
        [_quality(item) for item in listings],
        [MarketListingDetail(source_url=item.source_url) for item in listings],
        {
            str(item.source_url): (b"top", b"detail")
            for item in listings
        },
    )

    assert result.approved is False
    assert any("价格偏离" in reason for reason in result.reasons)
