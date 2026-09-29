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
    return any(
        token in normalized_prefix
        and any(token in reference for reference in references)
        for token in brand_tokens
    )


def _calibrate_vehicle_model(
    raw_value: str,
    subject_vehicle: SubjectVehicle,
    mappings: list[VehicleModelMapping],
    base_confidence: float,
) -> LicenseFieldCorrection | None:
    """只修复有法定型号和品牌词库共同支持的“牌”字误识别。"""

    try:
        legal_model = extract_legal_model(raw_value)
    except ValueError:
        return None
    mapping = next(
        (
            item
            for item in mappings
            if normalize_legal_model(item.legal_model) == legal_model
        ),
        None,
    )
    if mapping is None:
        return None

    match = re.search(re.escape(legal_model), raw_value.upper())
    if match is None or match.start() == 0:
        return None
    prefix = raw_value[: match.start()]
    if not prefix or prefix[-1] not in BRAND_SUFFIX_CONFUSIONS:
        return None
    if not _brand_supported(prefix[:-1], subject_vehicle, mapping):
        return None

    calibrated = prefix[:-1] + "牌" + raw_value[match.start():]
    return LicenseFieldCorrection(
        field_name="vehicle_model",
        raw_value=raw_value,
        calibrated_value=calibrated,
        rule="brand_suffix_confusion_before_legal_model",
        evidence=(
            f"法定型号{mapping.legal_model}命中本地车型映射，"
            f"品牌证据为{mapping.brand}，仅修正型号前一位易混淆字符"
        ),
        confidence=max(base_confidence, 0.98),
    )


def calibrate_license_fields(
    extracted_fields: dict[str, Any],
    ocr_lines: list[OCRTextLine],
    subject_vehicle: SubjectVehicle,
    mappings: list[VehicleModelMapping],
    high_risk_confidence_threshold: float = 0.85,
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
    for field_name in HIGH_RISK_FIELDS:
        if fields.get(field_name) and (
            confidences.get(field_name, 0.0)
            < high_risk_confidence_threshold
        ):
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
