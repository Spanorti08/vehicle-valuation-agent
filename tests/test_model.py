import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from vehicle_valuation.model import SubjectVehicle


DATA_PATH = (
    Path(__file__).parents[1]
    / "data"
    / "synthetic"
    / "subject_vehicle.json"
)


def load_sample_data() -> dict:
    return json.loads(DATA_PATH.read_text())


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