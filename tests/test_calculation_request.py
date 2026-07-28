from pathlib import Path

import pytest
from pydantic import ValidationError

from vehicle_valuation.loaders import (
    load_synthetic_calculation_request,
)
from vehicle_valuation.model import (
    ValuationCalculationRequest,
)


DATA_DIR = (
    Path(__file__).parents[1]
    / "data"
    / "synthetic"
)


def test_mismatched_case_ids_are_rejected() -> None:
    """案例与指数编号不一致时，计算请求应验证失败。"""

    request = load_synthetic_calculation_request(
        DATA_DIR,
        "2026-06-30",
    )
    data = request.model_dump(mode="json")
    data["comparison_indices"][0]["case_id"] = "CASE-X"

    with pytest.raises(
        ValidationError,
        match="市场案例与比较指数的case_id不一致",
    ):
        ValuationCalculationRequest.model_validate(data)


def test_duplicate_comparable_ids_are_rejected() -> None:
    """市场案例编号重复时，计算请求应验证失败。"""

    request = load_synthetic_calculation_request(
        DATA_DIR,
        "2026-06-30",
    )
    data = request.model_dump(mode="json")
    data["comparables"][1]["case_id"] = "CASE-A"

    with pytest.raises(
        ValidationError,
        match="市场案例中存在重复的case_id",
    ):
        ValuationCalculationRequest.model_validate(data)