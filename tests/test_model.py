import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from vehicle_valuation.market_scraper import (
    build_market_listing_snapshot,
)
from vehicle_valuation.model import (
    ComparableVehicle,
    MarketListing,
    SubjectVehicle,
)


DATA_PATH = (
    Path(__file__).parents[1]
    / "data"
    / "synthetic"
    / "subject_vehicle.json"
)

COMPARABLES_PATH = (
    Path(__file__).parents[1]
    / "data"
    / "synthetic"
    / "comparable_vehicles.json"
)


def load_sample_data() -> dict:
    return json.loads(DATA_PATH.read_text())


def load_comparable_data() -> list[dict]:
    return json.loads(COMPARABLES_PATH.read_text())


def test_valid_subject_vehicle() -> None:
    data = load_sample_data()

    vehicle = SubjectVehicle.model_validate(data)

    assert vehicle.asset_id == data["asset_id"]
    assert vehicle.mileage_km == data["mileage_km"]


def test_net_value_cannot_exceed_original_value() -> None:
    data = load_sample_data()

    data["book_value_net_cny"] = (
        data["book_value_original_cny"] + 1
    )

    with pytest.raises(
        ValidationError,
        match="账面净值不能大于账面原值",
    ):
        SubjectVehicle.model_validate(data)


def test_all_comparable_vehicles_are_valid() -> None:
    data = load_comparable_data()

    cases = [
        ComparableVehicle.model_validate(item)
        for item in data
    ]

    assert len(cases) >= 3


def test_comparable_price_must_be_positive() -> None:
    data = load_comparable_data()
    data[0]["price_cny"] = 0

    with pytest.raises(ValidationError):
        ComparableVehicle.model_validate(data[0])


def test_snapshot_only_updates_price_and_capture_time() -> None:
    """详情页快照不能用同款推荐车覆盖所选案例资料。"""

    listing = MarketListing(
        source_url="https://www.guazi.com/car-detail/test.html",
        vehicle_model="奔驰C级 2017款 C 200 L 运动版",
        registration_year=2017,
        mileage_km=84000,
        city="北京",
        price_cny=Decimal("86100"),
    )
    captured_at = datetime.fromisoformat(
        "2026-08-12T10:00:00+08:00"
    )

    snapshot = build_market_listing_snapshot(
        listing,
        Decimal("79500"),
        captured_at,
    )

    assert snapshot.price_cny == Decimal("79500")
    assert snapshot.captured_at == captured_at
    assert snapshot.vehicle_model == listing.vehicle_model
    assert snapshot.registration_year == 2017
    assert snapshot.mileage_km == 84000
    assert snapshot.city == "北京"


def test_snapshot_keeps_different_selected_cases_distinct() -> None:
    """多个案例更新价格后不能互相覆盖车型和里程。"""

    first = MarketListing(
        source_url="https://www.guazi.com/car-detail/first.html",
        vehicle_model="奔驰C级 2018款 C 200 L 运动版",
        registration_year=2018,
        mileage_km=58700,
        city="上海",
        price_cny=Decimal("78500"),
    )
    second = MarketListing(
        source_url="https://www.guazi.com/car-detail/second.html",
        vehicle_model="奔驰C级 2017款 C 200 L 运动版",
        registration_year=2017,
        mileage_km=84000,
        city="北京",
        price_cny=Decimal("84400"),
    )
    captured_at = datetime.fromisoformat(
        "2026-08-12T10:00:00+08:00"
    )

    snapshots = [
        build_market_listing_snapshot(
            first,
            Decimal("78000"),
            captured_at,
        ),
        build_market_listing_snapshot(
            second,
            Decimal("84000"),
            captured_at,
        ),
    ]

    assert snapshots[0].mileage_km == 58700
    assert snapshots[1].mileage_km == 84000
    assert snapshots[0].source_url != snapshots[1].source_url
