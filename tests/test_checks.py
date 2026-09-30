from pathlib import Path

from datetime import date

from vehicle_valuation.checks import (
    check_plate_number,
    check_vehicle_model,
    check_registration_month,
    run_initial_checks,
    run_license_subject_checks,
    run_structured_checks,
    vehicle_models_equivalent,
)
from vehicle_valuation.loaders import (
    load_synthetic_valuation_request,
)


DATA_DIR = (
    Path(__file__).parents[1]
    / "data"
    / "synthetic"
)


def test_matching_plate_numbers_have_no_issue() -> None:
    request = load_synthetic_valuation_request(
        DATA_DIR,
        "2026-06-30",
    )

    result = check_plate_number(request)

    assert result is None


def test_different_plate_numbers_create_issue() -> None:
    request = load_synthetic_valuation_request(
        DATA_DIR,
        "2026-06-30",
    )
    request.driving_license.plate_number = "豫A·DIFF1"

    result = check_plate_number(request)

    assert result is not None
    assert "车牌号不一致" in result


def test_matching_vehicle_models_have_no_issue() -> None:
    request = load_synthetic_valuation_request(
        DATA_DIR,
        "2026-06-30",
    )

    result = check_vehicle_model(request)

    assert result is None


def test_different_vehicle_models_create_issue() -> None:
    request = load_synthetic_valuation_request(
        DATA_DIR,
        "2026-06-30",
    )
    request.driving_license.vehicle_model = "ABC123"

    result = check_vehicle_model(request)

    assert result is not None
    assert "车辆型号可能不一致" in result


def test_same_legal_model_ignores_low_value_brand_text_differences() -> None:
    assert vehicle_models_equivalent(
        "梅赛德斯-奔驰牌BJ7204小轿车",
        "梅赛德斯 奔驰界 BJ7.204",
    )


def test_matching_registration_months_have_no_issue() -> None:
    request = load_synthetic_valuation_request(
        DATA_DIR,
        "2026-06-30",
    )

    result = check_registration_month(request)

    assert result is None


def test_different_registration_months_create_issue() -> None:
    request = load_synthetic_valuation_request(
        DATA_DIR,
        "2026-06-30",
    )
    request.driving_license.registration_date = date(
        2016,
        1,
        1,
    )

    result = check_registration_month(request)

    assert result is not None
    assert "注册年月不一致" in result


def test_initial_checks_return_empty_list_for_valid_data() -> None:
    """资料一致时，初始检查应返回空列表。"""

    request = load_synthetic_valuation_request(
        DATA_DIR,
        "2026-06-30",
    )

    issues = run_initial_checks(request)

    assert issues == []


def test_initial_checks_return_multiple_issues() -> None:
    """存在多处不一致时，应返回全部复核问题。"""

    request = load_synthetic_valuation_request(
        DATA_DIR,
        "2026-06-30",
    )
    request.driving_license.plate_number = "豫A·DIFF1"
    request.driving_license.vehicle_model = "ABC123"

    issues = run_initial_checks(request)

    assert len(issues) == 2


def test_structured_checks_show_sources_and_ocr_risk() -> None:
    request = load_synthetic_valuation_request(
        DATA_DIR,
        "2026-06-30",
    )
    request.driving_license.plate_number = "豫A·DIFF1"

    conflicts = run_structured_checks(request)

    plate_conflict = next(
        item for item in conflicts if item.field_name == "车牌号"
    )
    assert set(plate_conflict.source_values) == {"Excel", "行驶证/OCR"}
    assert plate_conflict.possible_ocr_error is True


def test_structured_checks_compare_inspection_mileage() -> None:
    request = load_synthetic_valuation_request(
        DATA_DIR,
        "2026-06-30",
    )
    request.inspection.actual_mileage_km += 1

    conflicts = run_structured_checks(request)

    assert any(item.field_name == "行驶里程" for item in conflicts)


def test_license_subject_checks_can_run_immediately_after_ocr() -> None:
    request = load_synthetic_valuation_request(
        DATA_DIR,
        "2026-06-30",
    )

    conflicts = run_license_subject_checks(
        request.subject_vehicle,
        request.driving_license,
    )

    assert conflicts == []
