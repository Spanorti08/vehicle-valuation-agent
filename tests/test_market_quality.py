from datetime import datetime
from decimal import Decimal

from vehicle_valuation.market_quality import score_market_cases
from vehicle_valuation.model import MarketListing


def make_listing(
    number: int,
    *,
    model: str = "奔驰C级 2018款 C 200 L",
    year: int = 2018,
    mileage: int = 80000,
    price: str = "160000",
    city: str = "北京",
) -> MarketListing:
    return MarketListing(
        source_url=f"https://example.com/case-{number}",
        vehicle_model=model,
        registration_year=year,
        mileage_km=mileage,
        city=city,
        price_cny=Decimal(price),
        captured_at=datetime.now().astimezone(),
    )


def test_complete_comparable_case_is_qualified() -> None:
    listing = make_listing(1)
    results = score_market_cases(
        listings=[listing],
        market_keyword="奔驰C级 2018款 C 200 L",
        target_year=2018,
        target_mileage_km=80000,
        preferred_cities={"北京"},
        page_valid_urls={str(listing.source_url)},
        year_tolerance=1,
        mileage_tolerance_km=50000,
        minimum_quality_score=70,
    )

    assert results[0].qualified is True
    assert results[0].total_score == 100


def test_case_outside_year_range_is_rejected() -> None:
    listing = make_listing(1, year=2014)
    result = score_market_cases(
        listings=[listing],
        market_keyword="奔驰C级 2018款 C 200 L",
        target_year=2018,
        target_mileage_km=80000,
        preferred_cities={"北京"},
        page_valid_urls={str(listing.source_url)},
        year_tolerance=1,
        mileage_tolerance_km=50000,
        minimum_quality_score=70,
    )[0]

    assert result.qualified is False
    assert any("年份" in reason for reason in result.rejection_reasons)


def test_duplicate_vehicle_signature_is_flagged() -> None:
    first = make_listing(1)
    duplicate = make_listing(2)
    results = score_market_cases(
        listings=[first, duplicate],
        market_keyword="奔驰C级 2018款 C 200 L",
        target_year=2018,
        target_mileage_km=80000,
        preferred_cities={"北京"},
        page_valid_urls={
            str(first.source_url),
            str(duplicate.source_url),
        },
        year_tolerance=1,
        mileage_tolerance_km=50000,
        minimum_quality_score=70,
    )

    assert results[0].qualified is True
    assert any(
        "疑似同一车辆重复发布" in warning
        for warning in results[1].risk_warnings
    )


def test_missing_page_snapshot_is_rejected() -> None:
    listing = make_listing(1)
    result = score_market_cases(
        listings=[listing],
        market_keyword="奔驰C级 2018款 C 200 L",
        target_year=2018,
        target_mileage_km=80000,
        preferred_cities={"北京"},
        page_valid_urls=set(),
        year_tolerance=1,
        mileage_tolerance_km=50000,
        minimum_quality_score=70,
    )[0]

    assert result.qualified is False
    assert result.page_validity_score == 0


def test_case_below_sixty_similarity_never_enters_candidates() -> None:
    """即使其他字段完整，年份/里程匹配分低于60也必须淘汰。"""

    listing = make_listing(1, year=2016, mileage=180000)
    result = score_market_cases(
        listings=[listing],
        market_keyword="奔驰C级 2018款 C 200 L",
        target_year=2018,
        target_mileage_km=80000,
        preferred_cities={"北京"},
        page_valid_urls={str(listing.source_url)},
        year_tolerance=2,
        mileage_tolerance_km=100000,
        minimum_quality_score=60,
        minimum_similarity_score=60,
    )[0]

    assert result.total_score >= 60
    assert result.similarity_score < 60
    assert result.qualified is False
    assert any(
        "综合匹配分低于60分" in reason
        for reason in result.rejection_reasons
    )
