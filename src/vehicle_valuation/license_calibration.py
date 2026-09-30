"""行驶证 OCR 的字段级、安全校准与审计记录。"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from vehicle_valuation.license_ocr import OCRTextLine
from vehicle_valuation.model import SubjectVehicle, VehicleModelMapping
from vehicle_valuation.model_mapping_retrieval import (
    extract_legal_model,
    normalize_legal_model,
)


REQUIRED_LICENSE_FIELDS = (
    "plate_number",
    "vehicle_type",
    "owner_name",
    "address",
    "use_character",
    "vehicle_model",
    "vin",
    "engine_number",
    "registration_date",
    "issue_date",
)
HIGH_RISK_FIELDS = {"plate_number", "vin", "registration_date"}
BRAND_SUFFIX_CONFUSIONS = {"界", "脾", "碑", "啤", "卑"}
OCR_IDENTIFIER_CONFUSION_GROUPS = (
    frozenset("0OQ"),
    frozenset("1IL"),
    frozenset("2Z"),
    frozenset("5S"),
    frozenset("6G"),
    frozenset("8B"),
)


class LicenseFieldCorrection(BaseModel):
    field_name: str
    raw_value: str
    calibrated_value: str
    rule: str
    evidence: str
    confidence: float = Field(ge=0, le=1)
    auto_applied: bool = True


class LicenseCalibrationResult(BaseModel):
    fields: dict[str, str | None]
    field_confidences: dict[str, float] = Field(default_factory=dict)
    corrections: list[LicenseFieldCorrection] = Field(default_factory=list)
    requires_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff]", "", value.upper())


def _is_reference_backed_ocr_match(
    observed: str,
    trusted: str,
    max_differences: int,
) -> bool:
    """只接受可由常见 OCR 混淆逐字符还原的等长标识符。"""

    observed_value = _normalize_identifier(observed)
    trusted_value = _normalize_identifier(trusted)
    if len(observed_value) != len(trusted_value):
        return False

    differences = 0
    for observed_char, trusted_char in zip(
        observed_value,
        trusted_value,
        strict=True,
    ):
        if observed_char == trusted_char:
            continue
        if not any(
            observed_char in group and trusted_char in group
            for group in OCR_IDENTIFIER_CONFUSION_GROUPS
        ):
            return False
        differences += 1

    return 0 < differences <= max_differences


def _within_one_substitution(left: str, right: str) -> bool:
    return (
        len(left) == len(right)
        and sum(a != b for a, b in zip(left, right, strict=True)) <= 1
    )


def estimate_field_confidences(
    fields: dict[str, str | None],
    ocr_lines: list[OCRTextLine],
) -> dict[str, float]:
    """用包含该字段文字的 OCR 行估算字段置信度。"""

    confidences: dict[str, float] = {}
    for field_name, value in fields.items():
        if not value:
            confidences[field_name] = 0.0
            continue
        compact_value = _compact(str(value))
        matched_scores = [
            line.confidence
            for line in ocr_lines
            if (
                _compact(line.text) in compact_value
                or compact_value in _compact(line.text)
            )
        ]
        confidences[field_name] = (
            min(matched_scores)
            if matched_scores
            else min(
                (line.confidence for line in ocr_lines),
                default=0.0,
            )
        )
    return confidences


def _brand_supported(
    prefix: str,
    subject_vehicle: SubjectVehicle,
    mapping: VehicleModelMapping,
) -> bool:
    normalized_prefix = re.sub(r"[^\u4e00-\u9fff]", "", prefix)
    references = (
        subject_vehicle.vehicle_name,
        subject_vehicle.manufacturer,
        mapping.brand,
        mapping.market_series,
    )
    brand_tokens = [
        token
        for token in re.split(r"[-·（）()\s]", mapping.brand)
        if len(token) >= 2
    ]
    for token in brand_tokens:
        if not any(token in reference for reference in references):
            continue
        if token in normalized_prefix:
            return True
        if any(
            _within_one_substitution(
                normalized_prefix[index:index + len(token)],
                token,
            )
            for index in range(
                max(0, len(normalized_prefix) - len(token) + 1)
            )
        ):
            return True
    return False


def _calibrate_vehicle_model(
    raw_value: str,
    subject_vehicle: SubjectVehicle,
    mappings: list[VehicleModelMapping],
    base_confidence: float,
) -> LicenseFieldCorrection | None:
    """用法定型号和品牌证据统一低风险车型 OCR 差异。"""

    try:
        legal_model = extract_legal_model(raw_value)
    except ValueError:
        return None
    matched_mappings = [
        item
        for item in mappings
        if (
            normalize_legal_model(item.legal_model) == legal_model
            or _is_reference_backed_ocr_match(
                legal_model,
                normalize_legal_model(item.legal_model),
                max_differences=2,
            )
        )
    ]
    matched_legal_models = {
        normalize_legal_model(item.legal_model)
        for item in matched_mappings
    }
    if len(matched_legal_models) != 1:
        return None
    mapping = matched_mappings[0]

    match = re.search(
        r"[A-Z]{1,4}\d[A-Z0-9.-]*",
        raw_value.upper(),
    )
    if (
        match is None
        or match.start() == 0
    ):
        return None
    prefix = raw_value[: match.start()]
    brand_prefix = (
        prefix[:-1]
        if prefix and prefix[-1] in BRAND_SUFFIX_CONFUSIONS | {"牌"}
        else prefix
    )
    if brand_prefix and not _brand_supported(
        brand_prefix,
        subject_vehicle,
        mapping,
    ):
        return None

    calibrated = f"{mapping.brand}牌{mapping.legal_model}"
    if calibrated == raw_value:
        return None
    return LicenseFieldCorrection(
        field_name="vehicle_model",
        raw_value=raw_value,
        calibrated_value=calibrated,
        rule="reference_backed_vehicle_model_normalization",
        evidence=(
            f"法定型号{mapping.legal_model}命中本地车型映射，"
            f"品牌证据为{mapping.brand}；统一品牌轻微 OCR 错字、"
            "通用后缀及型号标点或字母数字混淆"
        ),
        confidence=max(base_confidence, 0.98),
    )


def calibrate_license_fields(
    extracted_fields: dict[str, Any],
    ocr_lines: list[OCRTextLine],
    subject_vehicle: SubjectVehicle,
    mappings: list[VehicleModelMapping],
    high_risk_confidence_threshold: float = 0.70,
) -> LicenseCalibrationResult:
    """校准安全字段；缺失或高风险低置信度字段升级人工复核。"""

    fields: dict[str, str | None] = {
        key: (
            str(value).strip()
            if value is not None and str(value).strip()
            else None
        )
        for key, value in extracted_fields.items()
    }
    confidences = estimate_field_confidences(fields, ocr_lines)
    corrections: list[LicenseFieldCorrection] = []

    for field_name in ("plate_number", "vin", "engine_number"):
        raw_value = fields.get(field_name)
        if not raw_value:
            continue
        calibrated = _compact(raw_value).replace("·", "")
        if calibrated != raw_value:
            corrections.append(
                LicenseFieldCorrection(
                    field_name=field_name,
                    raw_value=raw_value,
                    calibrated_value=calibrated,
                    rule="safe_format_normalization",
                    evidence="仅删除空格或分隔点并统一英文字母大小写",
                    confidence=confidences.get(field_name, 0.0),
                )
            )
            fields[field_name] = calibrated

    trusted_identifiers = {
        "plate_number": subject_vehicle.plate_number,
        "vin": subject_vehicle.vin,
    }
    for field_name, trusted_value in trusted_identifiers.items():
        observed_value = fields.get(field_name)
        if not observed_value or not trusted_value:
            continue
        if _is_reference_backed_ocr_match(
            observed_value,
            trusted_value,
            max_differences=1 if field_name == "plate_number" else 2,
        ):
            calibrated = _normalize_identifier(trusted_value)
            corrections.append(
                LicenseFieldCorrection(
                    field_name=field_name,
                    raw_value=observed_value,
                    calibrated_value=calibrated,
                    rule="reference_backed_identifier_ocr_correction",
                    evidence=(
                        f"OCR 值仅包含常见字母数字混淆，"
                        f"可唯一还原为 Excel 中的{field_name}"
                    ),
                    confidence=max(confidences.get(field_name, 0.0), 0.98),
                )
            )
            fields[field_name] = calibrated

    raw_model = fields.get("vehicle_model")
    if raw_model:
        correction = _calibrate_vehicle_model(
            raw_model,
            subject_vehicle,
            mappings,
            confidences.get("vehicle_model", 0.0),
        )
        if correction is not None:
            fields["vehicle_model"] = correction.calibrated_value
            corrections.append(correction)

    review_reasons = [
        f"{field_name}未识别"
        for field_name in REQUIRED_LICENSE_FIELDS
        if not fields.get(field_name)
    ]
    trusted_matches = {
        "plate_number": (
            _compact(fields.get("plate_number") or "").replace("·", "")
            == _compact(subject_vehicle.plate_number).replace("·", "")
        ),
        "registration_date": (
            bool(fields.get("registration_date"))
            and str(fields["registration_date"])[:7]
            == subject_vehicle.in_service_date
        ),
        "vin": (
            bool(subject_vehicle.vin)
            and _compact(fields.get("vin") or "")
            == _compact(subject_vehicle.vin or "")
        ),
    }
    for field_name in HIGH_RISK_FIELDS:
        if fields.get(field_name) and (
            confidences.get(field_name, 0.0)
            < high_risk_confidence_threshold
        ) and not trusted_matches[field_name]:
            review_reasons.append(
                f"{field_name} OCR置信度"
                f"{confidences.get(field_name, 0.0):.0%}低于"
                f"{high_risk_confidence_threshold:.0%}"
            )

    return LicenseCalibrationResult(
        fields=fields,
        field_confidences=confidences,
        corrections=corrections,
        requires_review=bool(review_reasons),
        review_reasons=review_reasons,
    )
