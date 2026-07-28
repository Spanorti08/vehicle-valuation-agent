import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from vehicle_valuation.model import ComparableVehicle, SubjectVehicle


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