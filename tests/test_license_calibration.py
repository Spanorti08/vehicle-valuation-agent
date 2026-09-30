import json
from pathlib import Path

from vehicle_valuation.license_calibration import calibrate_license_fields
from vehicle_valuation.license_ocr import OCRTextLine
from vehicle_valuation.model import SubjectVehicle, VehicleModelMapping


ROOT = Path(__file__).parents[1]


def _subject() -> SubjectVehicle:
    payload = json.loads(
        (ROOT / "data" / "synthetic" / "subject_vehicle.json").read_text()
    )
    payload["vehicle_name"] = "北京奔驰C级轿车"
    payload["manufacturer"] = "北京奔驰汽车有限公司"
    return SubjectVehicle.model_validate(payload)


def _mapping() -> VehicleModelMapping:
    return VehicleModelMapping.model_validate(
        json.loads(
            (ROOT / "data" / "public" / "vehicle_model_mappings.json").read_text()
        )[0]
    )


def _complete_fields(vehicle_model: str = "奔驰界BJ7204") -> dict:
    return {
        "plate_number": "京A12345",
        "vehicle_type": "小型轿车",
        "owner_name": "测试公司",
        "address": "北京市朝阳区测试路1号",
        "use_character": "非营运",
        "vehicle_model": vehicle_model,
        "vin": "LE4WG4CB0HL000001",
        "engine_number": "123456",
        "registration_date": "2018-01-01",
        "issue_date": "2018-01-02",
    }


def _lines(fields: dict, confidence: float = 0.99) -> list[OCRTextLine]:
    return [
        OCRTextLine(text=str(value), confidence=confidence)
        for value in fields.values()
        if value
    ]


def test_reference_backed_brand_suffix_error_is_auto_corrected() -> None:
    fields = _complete_fields("梅赛德斯-奔驰界BJ7.204")

    result = calibrate_license_fields(
        fields,
        _lines(fields),
        _subject(),
        [_mapping()],
    )

    assert result.fields["vehicle_model"] == "梅赛德斯-奔驰牌BJ7204"
    assert result.requires_review is False
    assert result.corrections[-1].raw_value == "梅赛德斯-奔驰界BJ7.204"
    assert result.corrections[-1].rule == (
        "reference_backed_vehicle_model_normalization"
    )


def test_brand_typo_and_model_code_ocr_confusion_are_auto_corrected() -> None:
    fields = _complete_fields("梅赛德斯-奔弛牌BJ72O4")

    result = calibrate_license_fields(
        fields,
        _lines(fields),
        _subject(),
        [_mapping()],
    )

    assert result.fields["vehicle_model"] == "梅赛德斯-奔驰牌BJ7204"
    assert result.requires_review is False


def test_plate_and_vin_ocr_confusions_matching_excel_are_corrected() -> None:
    subject = _subject()
    subject.vin = "LE4WG4CB0HL000001"
    fields = _complete_fields("奔驰牌BJ7204")
    fields["plate_number"] = subject.plate_number.replace("1", "I", 1)
    fields["vin"] = subject.vin.replace("0", "O", 1)

    result = calibrate_license_fields(
        fields,
        _lines(fields),
        subject,
        [_mapping()],
    )

    assert result.fields["plate_number"] == subject.plate_number.replace("·", "")
    assert result.fields["vin"] == subject.vin
    assert result.requires_review is False


def test_non_confusable_identifier_difference_is_not_auto_corrected() -> None:
    subject = _subject()
    fields = _complete_fields("奔驰牌BJ7204")
    fields["plate_number"] = "京A92345"

    result = calibrate_license_fields(
        fields,
        _lines(fields),
        subject,
        [_mapping()],
    )

    assert result.fields["plate_number"] == "京A92345"


def test_unknown_brand_text_is_not_silently_corrected() -> None:
    fields = _complete_fields("未知界BJ7204")

    result = calibrate_license_fields(
        fields,
        _lines(fields),
        _subject(),
        [_mapping()],
    )

    assert result.fields["vehicle_model"] == "未知界BJ7204"
    assert not any(
        item.field_name == "vehicle_model"
        for item in result.corrections
    )


def test_low_confidence_vin_requires_human_review() -> None:
    fields = _complete_fields("奔驰牌BJ7204")
    lines = _lines(fields)
    for line in lines:
        if line.text == fields["vin"]:
            line.confidence = 0.60

    result = calibrate_license_fields(
        fields,
        lines,
        _subject(),
        [_mapping()],
    )

    assert result.requires_review is True
    assert any("vin OCR置信度" in reason for reason in result.review_reasons)


def test_missing_required_field_requires_human_review() -> None:
    fields = _complete_fields()
    fields["engine_number"] = None

    result = calibrate_license_fields(
        fields,
        _lines(fields),
        _subject(),
        [_mapping()],
    )

    assert result.requires_review is True
    assert "engine_number未识别" in result.review_reasons


def test_low_confidence_date_matching_excel_is_auto_accepted() -> None:
    fields = _complete_fields("奔驰牌BJ7204")
    fields["registration_date"] = "2015-03-18"
    lines = _lines(fields)
    for line in lines:
        if line.text == fields["registration_date"]:
            line.confidence = 0.55

    result = calibrate_license_fields(
        fields,
        lines,
        _subject(),
        [_mapping()],
    )

    assert not any(
        "registration_date OCR置信度" in reason
        for reason in result.review_reasons
    )


def test_low_confidence_plate_matching_excel_is_auto_accepted() -> None:
    fields = _complete_fields("奔驰牌BJ7204")
    fields["plate_number"] = _subject().plate_number
    lines = _lines(fields)
    for line in lines:
        if line.text == fields["plate_number"]:
            line.confidence = 0.50

    result = calibrate_license_fields(
        fields,
        lines,
        _subject(),
        [_mapping()],
    )

    assert not any(
        "plate_number OCR置信度" in reason
        for reason in result.review_reasons
    )
