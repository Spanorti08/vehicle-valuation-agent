"""离线、可重复的工作流能力评测。

本模块只使用合成输入和本地已有的 RAG 评测结果，不访问网络、Ollama
或真实车辆资料。它评测的是 OCR 后字段校准、异常分流、受控市场搜索和
自动 Top 3 策略，不把这些结果误写成原始图片 OCR 准确率或生产通过率。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from vehicle_valuation.case_selection import evaluate_automatic_case_selection
from vehicle_valuation.checks import run_license_subject_checks
from vehicle_valuation.license_calibration import calibrate_license_fields
from vehicle_valuation.license_ocr import OCRTextLine
from vehicle_valuation.market_agent import (
    ControlledMarketAgent,
    MarketAgentConfig,
    MarketAgentState,
    RuleBasedMarketAgentPlanner,
)
from vehicle_valuation.model import (
    DrivingLicenseData,
    MarketListing,
    MarketListingDetail,
    SubjectVehicle,
    VehicleModelMapping,
)


CRITICAL_LICENSE_FIELDS = (
    "plate_number",
    "vehicle_model",
    "vin",
    "registration_date",
)


def _subject_vehicle() -> SubjectVehicle:
    return SubjectVehicle(
        sequence_number=1,
        asset_id="EVAL-CAR-001",
        plate_number="京A12345",
        vehicle_name="梅赛德斯-奔驰牌BJ7204小轿车",
        manufacturer="北京奔驰汽车有限公司",
        vin="LE4WG4CB0HL000001",
        unit="辆",
        quantity=1,
        purchase_date="2018-03",
        in_service_date="2018-03",
        mileage_km=80_000,
        book_value_original_cny=Decimal("300000"),
        book_value_net_cny=Decimal("80000"),
    )


def _mapping() -> VehicleModelMapping:
    return VehicleModelMapping(
        mapping_id="EVAL-MAP-001",
        legal_model="BJ7204",
        brand="梅赛德斯-奔驰",
        market_series="奔驰C级",
        market_keyword="C 200 L",
        model_year="2017款",
        evidence_summary="合成评测用法定型号映射。",
        source_title="合成评测来源",
        source_url="https://example.com/model-mapping",
    )


def _base_license_fields() -> dict[str, str]:
    return {
        "plate_number": "京A12345",
        "vehicle_type": "小型轿车",
        "owner_name": "测试公司",
        "address": "北京市朝阳区",
        "use_character": "非营运",
        "vehicle_model": "梅赛德斯-奔驰牌BJ7204",
        "vin": "LE4WG4CB0HL000001",
        "engine_number": "EVAL123456",
        "registration_date": "2018-03-05",
        "issue_date": "2018-03-05",
    }


def _license_scenarios() -> list[dict[str, Any]]:
    base = _base_license_fields()

    def scenario(
        scenario_id: str,
        changes: dict[str, str | None],
        *,
        expected_manual: bool,
        expects_auto_correction: bool = False,
        low_confidence_field: str | None = None,
    ) -> dict[str, Any]:
        fields: dict[str, str | None] = {**base, **changes}
        return {
            "scenario_id": scenario_id,
            "fields": fields,
            "expected_fields": base,
            "expected_manual": expected_manual,
            "expects_auto_correction": expects_auto_correction,
            "low_confidence_field": low_confidence_field,
        }

    return [
        scenario("exact_match", {}, expected_manual=False),
        scenario(
            "brand_suffix_and_model_punctuation",
            {"vehicle_model": "梅赛德斯-奔驰界BJ7.204"},
            expected_manual=False,
            expects_auto_correction=True,
        ),
        scenario(
            "plate_letter_digit_confusion",
            {"plate_number": "京A1234S"},
            expected_manual=False,
            expects_auto_correction=True,
        ),
        scenario(
            "vin_letter_digit_confusion",
            {"vin": "LE4WG4CB0HLO00001"},
            expected_manual=False,
            expects_auto_correction=True,
        ),
        scenario(
            "low_confidence_but_reference_matches",
            {},
            expected_manual=False,
            low_confidence_field="registration_date",
        ),
        scenario(
            "missing_required_engine_number",
            {"engine_number": None},
            expected_manual=True,
        ),
        scenario(
            "material_plate_conflict",
            {"plate_number": "京B99999"},
            expected_manual=True,
        ),
        scenario(
            "low_confidence_registration_conflict",
            {"registration_date": "2017-03-05"},
            expected_manual=True,
            low_confidence_field="registration_date",
        ),
    ]


def _ocr_lines(
    fields: dict[str, str | None],
    low_confidence_field: str | None,
) -> list[OCRTextLine]:
    return [
        OCRTextLine(
            text=value,
            confidence=(
                0.55 if field_name == low_confidence_field else 0.98
            ),
        )
        for field_name, value in fields.items()
        if value
    ]


def _comparable_value(value: str | None) -> str:
    return (value or "").replace("·", "").replace(" ", "").upper()


def evaluate_document_intake() -> dict[str, Any]:
    """评测 OCR 后字段校准、资料比对和人工异常分流。"""

    subject = _subject_vehicle()
    mappings = [_mapping()]
    records: list[dict[str, Any]] = []
    auto_field_correct = 0
    auto_field_total = 0
    correction_successes = 0
    correction_cases = 0
    manual_routing_correct = 0
    auto_passes = 0

    for item in _license_scenarios():
        result = calibrate_license_fields(
            item["fields"],
            _ocr_lines(item["fields"], item["low_confidence_field"]),
            subject,
            mappings,
        )
        conflicts = []
        schema_valid = True
        try:
            license_data = DrivingLicenseData.model_validate(result.fields)
            conflicts = run_license_subject_checks(subject, license_data)
        except ValidationError:
            schema_valid = False

        actual_manual = (
            result.requires_review or bool(conflicts) or not schema_valid
        )
        if not actual_manual:
            auto_passes += 1
        if actual_manual == item["expected_manual"]:
            manual_routing_correct += 1

        field_matches = {
            field_name: _comparable_value(result.fields.get(field_name))
            == _comparable_value(item["expected_fields"][field_name])
            for field_name in CRITICAL_LICENSE_FIELDS
        }
        if not item["expected_manual"]:
            auto_field_correct += sum(field_matches.values())
            auto_field_total += len(field_matches)
        if item["expects_auto_correction"]:
            correction_cases += 1
            if all(field_matches.values()) and not actual_manual:
                correction_successes += 1

        records.append(
            {
                "scenario_id": item["scenario_id"],
                "expected_manual": item["expected_manual"],
                "actual_manual": actual_manual,
                "schema_valid": schema_valid,
                "critical_fields_correct": all(field_matches.values()),
                "correction_rules": [
                    correction.rule for correction in result.corrections
                ],
                "review_reasons": result.review_reasons,
                "conflicts": [conflict.message for conflict in conflicts],
            }
        )

    scenario_count = len(records)
    auto_resolvable_count = sum(
        not item["expected_manual"] for item in _license_scenarios()
    )
    return {
        "scope": "OCR后字段校准与异常分流，不是原始图片OCR准确率",
        "scenario_count": scenario_count,
        "auto_resolvable_case_count": auto_resolvable_count,
        "auto_resolvable_critical_field_accuracy": round(
            auto_field_correct / auto_field_total, 4
        ),
        "auto_correction_success_rate": round(
            correction_successes / correction_cases, 4
        ),
        "manual_routing_accuracy": round(
            manual_routing_correct / scenario_count, 4
        ),
        "scenario_mix_auto_pass_rate": round(auto_passes / scenario_count, 4),
        "records": records,
    }


class _BatchSearchBackend:
    """按城市批次返回合成结果，确保评测完全离线。"""

    def __init__(self, responses: dict[tuple[str, ...], tuple[list, list]]):
        self.responses = responses

    def search(self, city_paths, series_path):
        del series_path
        return self.responses.get(tuple(city_paths), ([], []))


class _RetrySearchBackend:
    def __init__(self, listings: list[MarketListing]):
        self.listings = listings
        self.call_count = 0

    def search(self, city_paths, series_path):
        del city_paths, series_path
        self.call_count += 1
        if self.call_count == 1:
            return [], ["bj"]
        return self.listings, []


def _listing(
    listing_id: str,
    *,
    year: int = 2018,
    mileage_km: int = 80_000,
    price_cny: int = 80_000,
) -> MarketListing:
    return MarketListing(
        source_url=f"https://example.com/listing/{listing_id}",
        vehicle_model="奔驰C级 2018款 C 200 L 运动版",
        registration_year=year,
        mileage_km=mileage_km,
        city="北京",
        price_cny=Decimal(price_cny),
    )


def _initial_state() -> MarketAgentState:
    return MarketAgentState(
        market_keyword="C 200 L",
        series_path="benz/benz-c",
        target_year=2018,
        target_mileage_km=80_000,
    )


def _top3_policy_approves(state: MarketAgentState) -> bool:
    selection = evaluate_automatic_case_selection(
        state.candidates,
        state.quality_assessments,
        [
            MarketListingDetail(source_url=item.source_url)
            for item in state.candidates
        ],
        {
            str(item.source_url): (b"list", b"detail")
            for item in state.candidates
        },
    )
    return selection.approved


def evaluate_market_agent() -> dict[str, Any]:
    """评测 LangGraph 搜索分支、有限重试、硬门槛和自动 Top 3。"""

    first = _listing("first")
    second = _listing("second", mileage_km=85_000)
    third = _listing("third", mileage_km=75_000)
    low_similarity = [
        _listing(f"low-{index}", year=2010, mileage_km=300_000 + index)
        for index in range(3)
    ]
    scenarios = [
        {
            "scenario_id": "initial_batch_succeeds",
            "expected_success": True,
            "backend": _BatchSearchBackend(
                {("bj",): ([first, second, third], [])}
            ),
            "config": MarketAgentConfig(city_batches=[["bj"]]),
        },
        {
            "scenario_id": "expand_city_then_succeed",
            "expected_success": True,
            "backend": _BatchSearchBackend(
                {
                    ("bj",): ([first], []),
                    ("sh",): ([second, third], []),
                }
            ),
            "config": MarketAgentConfig(city_batches=[["bj"], ["sh"]]),
        },
        {
            "scenario_id": "retry_then_succeed",
            "expected_success": True,
            "backend": _RetrySearchBackend([first, second, third]),
            "config": MarketAgentConfig(
                city_batches=[["bj"]], max_retries_per_city=1
            ),
        },
        {
            "scenario_id": "insufficient_cases_pause",
            "expected_success": False,
            "backend": _BatchSearchBackend({("bj",): ([first], [])}),
            "config": MarketAgentConfig(city_batches=[["bj"]]),
        },
        {
            "scenario_id": "below_similarity_floor_pause",
            "expected_success": False,
            "backend": _BatchSearchBackend(
                {("bj",): (low_similarity, [])}
            ),
            "config": MarketAgentConfig(city_batches=[["bj"]]),
        },
    ]

    records: list[dict[str, Any]] = []
    successful_rounds: list[int] = []
    solvable_successes = 0
    auto_top3_successes = 0
    expected_outcomes = 0
    floor_rejections = 0

    for item in scenarios:
        agent = ControlledMarketAgent(
            planner=RuleBasedMarketAgentPlanner(),
            search_backend=item["backend"],
            config=item["config"],
        )
        try:
            state = agent.run_until_pause(_initial_state())
        finally:
            agent.close()

        actual_success = state.status == "candidates_ready"
        top3_approved = actual_success and _top3_policy_approves(state)
        if item["expected_success"] and actual_success:
            solvable_successes += 1
            successful_rounds.append(state.search_round)
        if item["expected_success"] and top3_approved:
            auto_top3_successes += 1
        if actual_success == item["expected_success"]:
            expected_outcomes += 1
        if item["scenario_id"] == "below_similarity_floor_pause":
            floor_rejections = sum(
                any("匹配分低于60分" in reason for reason in rejected.reasons)
                for rejected in state.rejected_cases
            )

        records.append(
            {
                "scenario_id": item["scenario_id"],
                "expected_success": item["expected_success"],
                "status": state.status,
                "search_rounds": state.search_round,
                "qualified_cases": len(state.candidates),
                "automatic_top3_approved": top3_approved,
                "rejected_cases": len(state.rejected_cases),
            }
        )

    solvable_count = sum(item["expected_success"] for item in scenarios)
    return {
        "scope": "离线合成搜索后端；评测图路由、预算、门槛和自动选择策略",
        "scenario_count": len(scenarios),
        "solvable_scenario_count": solvable_count,
        "solvable_search_success_rate": round(
            solvable_successes / solvable_count, 4
        ),
        "expected_outcome_accuracy": round(
            expected_outcomes / len(scenarios), 4
        ),
        "automatic_top3_ready_rate": round(
            auto_top3_successes / solvable_count, 4
        ),
        "average_search_rounds_successful": round(
            sum(successful_rounds) / len(successful_rounds), 2
        ),
        "below_similarity_floor_block_rate": round(
            floor_rejections / len(low_similarity), 4
        ),
        "minimum_similarity_score": 60,
        "records": records,
    }


def load_rag_baseline(project_root: Path) -> dict[str, Any]:
    """读取已经由独立测试集生成的 RAG 结果，不在此重复调模型。"""

    result_path = project_root / "data/rag/evaluation_results.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    return {
        "scope": "已有独立测试集检索结果；10题调参、5题测试",
        "source_file": str(result_path.relative_to(project_root)),
        "question_count": payload["question_count"],
        "tuning_question_count": payload["tuning_question_count"],
        "test_question_count": payload["test_question_count"],
        "selected_weights": payload["selected_weights"],
        "test_results": [
            {
                key: result[key]
                for key in (
                    "retriever",
                    "question_count",
                    "hit_rate_at_3",
                    "mean_recall_at_3",
                    "mrr_at_3",
                )
            }
            for result in payload["test_results"]
        ],
    }


def run_workflow_evaluation(project_root: Path) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_type": "offline_synthetic_and_stored_independent_test",
        "document_intake": evaluate_document_intake(),
        "market_agent": evaluate_market_agent(),
        "rag_retrieval": load_rag_baseline(project_root),
        "limitations": [
            "字段校准样本是人工构造的常见错误，不代表真实图片OCR准确率。",
            "市场搜索使用离线合成后端，不代表公开网站实时可用率。",
            "自动通过率取决于本评测中的正常/异常样本比例，不外推生产数据。",
            "RAG数字来自仓库内固定的5题独立测试集，样本量仍然较小。",
        ],
    }
