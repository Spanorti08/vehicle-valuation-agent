from decimal import Decimal
from pathlib import Path

from vehicle_valuation.adjustment_ai import generate_comparison_suggestion
from vehicle_valuation.adjustment_rules import load_adjustment_rule_set
from vehicle_valuation.loaders import load_synthetic_valuation_request
from vehicle_valuation.model import (
    AIComparisonSuggestion,
    MarketListing,
    MarketListingDetail,
)


ROOT = Path(__file__).parents[1]


def _factor(difference: int = 0) -> dict:
    return {
        "direction": "same",
        "grade_difference": difference,
        "suggested_index": 100,
        "reason": "依据详情字段判断",
        "confidence": 0.8,
        "evidence_sufficient": True,
    }


class FakeProvider:
    def generate(self, prompt, response_model):
        assert "当前项目正式规则" in prompt
        payload = {
            "case_id": "CASE-1",
            "transaction": _factor(),
            "inspection": _factor(),
            "transfer": _factor(),
            "vehicle_use": _factor(),
            "exterior": _factor(2),
            "interior": _factor(1),
            "hardware": _factor(-1),
        }
        return response_model.model_validate(payload)


class BrokenProvider:
    def generate(self, prompt, response_model):
        raise RuntimeError("offline")


def _inputs():
    request = load_synthetic_valuation_request(
        ROOT / "data" / "synthetic",
        "2026-06-30",
    )
    listing = MarketListing(
        source_url="https://example.com/case-1",
        vehicle_model="测试车型",
        registration_year=2018,
        mileage_km=80_000,
        city="北京",
        price_cny=Decimal("80000"),
    )
    rules = load_adjustment_rule_set(
        ROOT / "data" / "public" / "adjustment_rules.json"
    )
    return request, listing, rules


def test_python_recalculates_index_from_evidenced_grade_difference() -> None:
    request, listing, rules = _inputs()
    detail = MarketListingDetail(
        source_url=listing.source_url,
        exterior_condition="外观检测良好",
        interior_condition=None,
        engine_transmission_condition="发动机运转正常",
    )

    result = generate_comparison_suggestion(
        FakeProvider(), rules, "CASE-1", request, listing, detail
    )

    assert result.exterior.suggested_index == 106
    assert result.exterior.direction == "case_better"
    assert result.interior.suggested_index == 100
    assert result.interior.evidence_sufficient is False
    assert result.hardware.suggested_index == 97


def test_model_failure_returns_all_insufficient_indices() -> None:
    request, listing, rules = _inputs()

    result = generate_comparison_suggestion(
        BrokenProvider(),
        rules,
        "CASE-1",
        request,
        listing,
        MarketListingDetail(source_url=listing.source_url),
    )

    for field_name in AIComparisonSuggestion.model_fields:
        if field_name == "case_id":
            continue
        factor = getattr(result, field_name)
        assert factor.suggested_index == 100
        assert factor.evidence_sufficient is False
