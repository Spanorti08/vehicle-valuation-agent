from datetime import datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook

from vehicle_valuation.excel_exporter import (
    clear_hidden_legacy_formula_errors,
    validate_case_export_inputs,
)
from vehicle_valuation.model import (
    MarketListing,
    MarketListingDetail,
)


def make_listing(case_id: int) -> MarketListing:
    """构造一个导出校验使用的市场案例。"""

    return MarketListing(
        source_url=(
            "https://www.guazi.com/car-detail/"
            f"case-{case_id}.html"
        ),
        vehicle_model=f"测试车型{case_id}",
        registration_year=2018,
        mileage_km=80000 + case_id,
        city="北京",
        price_cny=Decimal("80000") + case_id,
        captured_at=datetime.fromisoformat(
            "2026-08-12T10:00:00+08:00"
        ),
    )


def make_detail(listing: MarketListing) -> MarketListingDetail:
    """为一个市场案例构造URL一致的详情。"""

    return MarketListingDetail(
        source_url=listing.source_url,
    )


def test_case_export_inputs_require_matching_urls() -> None:
    """案例、详情和截图URL全部对应时才允许导出。"""

    listings = [make_listing(index) for index in range(1, 4)]
    details = [make_detail(listing) for listing in listings]
    screenshots = {
        str(listing.source_url): (
            f"top-{index}".encode(),
            f"detail-{index}".encode(),
        )
        for index, listing in enumerate(
            listings,
            start=1,
        )
    }

    validate_case_export_inputs(
        listings,
        details,
        screenshots,
    )


def test_case_export_inputs_reject_duplicate_listing() -> None:
    """重复车源不能进入Excel和报告。"""

    listings = [make_listing(1), make_listing(2), make_listing(2)]
    details = [make_detail(listing) for listing in listings]
    screenshots = {
        str(listing.source_url): (
            f"top-{index}".encode(),
            f"detail-{index}".encode(),
        )
        for index, listing in enumerate(
            listings,
            start=1,
        )
    }

    with pytest.raises(
        ValueError,
        match="重复的车源链接",
    ):
        validate_case_export_inputs(
            listings,
            details,
            screenshots,
        )


def test_case_export_inputs_reject_identical_screenshots() -> None:
    """不同案例不能使用完全相同的两张截图。"""

    listings = [make_listing(index) for index in range(1, 4)]
    details = [make_detail(listing) for listing in listings]
    screenshots = {
        str(listing.source_url): (b"same-top", b"same-detail")
        for listing in listings
    }

    with pytest.raises(
        ValueError,
        match="完全相同的截图",
    ):
        validate_case_export_inputs(
            listings,
            details,
            screenshots,
        )


def test_hidden_legacy_formula_errors_are_cleared() -> None:
    """隐藏旧模板页的失效引用不应留在最终Excel中。"""

    workbook = Workbook()
    hidden_sheet = workbook.active
    hidden_sheet.title = "数据校验"
    hidden_sheet.sheet_state = "hidden"
    hidden_sheet["A1"] = "=SUM(旧表!#REF!)"

    visible_sheet = workbook.create_sheet("计算表")
    visible_sheet["A1"] = "=1+1"

    cleared_count = clear_hidden_legacy_formula_errors(
        workbook
    )

    assert cleared_count == 1
    assert hidden_sheet["A1"].value == 0
    assert visible_sheet["A1"].value == "=1+1"
