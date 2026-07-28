from decimal import Decimal
from pathlib import Path

from vehicle_valuation.calculation import (
    calculate_adjusted_price,
    calculate_final_value,
)
from vehicle_valuation.loaders import load_synthetic_calculation_request


DATA_DIR = (
    Path(__file__).parents[1]
    / "data"
    / "synthetic"
)


def test_calculate_first_adjusted_price() -> None:
    """验证案例1的修正后价格是21000元。"""

    request = load_synthetic_calculation_request(
        DATA_DIR,
        "2026-06-30",
    )

    result = calculate_adjusted_price(
        request.comparables[0],
        request.comparison_indices[0],
    )

    assert result == Decimal("21000")


def test_calculate_final_value() -> None:
    """验证三个案例计算得到的最终评估值为21600元。"""

    request = load_synthetic_calculation_request(
        DATA_DIR,
        "2026-06-30",
    )

    result = calculate_final_value(
        request.comparables,
        request.comparison_indices,
    )

    assert result == Decimal("21600")