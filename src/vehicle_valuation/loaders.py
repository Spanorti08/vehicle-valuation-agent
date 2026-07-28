import json
from pathlib import Path
from typing import Any

from .model import (
    ValuationCalculationRequest,
    ValuationRequest,
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_synthetic_valuation_request(
    data_dir: Path,
    valuation_date: str,
) -> ValuationRequest:
    request_data = {
        "valuation_date": valuation_date,
        "subject_vehicle": load_json(
            data_dir / "subject_vehicle.json"
        ),
        "driving_license": load_json(
            data_dir / "driving_license.json"
        ),
        "inspection": load_json(
            data_dir / "vehicle_inspection.json"
        ),
    }

    return ValuationRequest.model_validate(request_data)


def load_synthetic_calculation_request(
    data_dir: Path,
    valuation_date: str,
) -> ValuationCalculationRequest:
    """加载合成数据并组成一份完整的市场法计算请求。"""

    initial_request = load_synthetic_valuation_request(
        data_dir,
        valuation_date,
    )

    calculation_data = {
        "initial_request": initial_request,
        "comparables": load_json(
            data_dir / "comparable_vehicles.json"
        ),
        "comparison_indices": load_json(
            data_dir / "comparison_indices.json"
        ),
    }

    return ValuationCalculationRequest.model_validate(
        calculation_data
    )