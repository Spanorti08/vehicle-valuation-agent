"""调节参数的异常驱动人工复核策略。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from vehicle_valuation.model import AIComparisonSuggestion


class AdjustmentReviewDecision(BaseModel):
    requires_review: bool
    reasons: list[str] = Field(default_factory=list)


def evaluate_adjustment_review(
    suggestions: list[AIComparisonSuggestion],
    minimum_confidence: float = 0.65,
    maximum_grade_difference: int = 2,
) -> AdjustmentReviewDecision:
    """证据不足但指数为100可安全直通，其余异常升级人工。"""

    reasons: list[str] = []
    for suggestion in suggestions:
        for field_name in (
            "transaction",
            "inspection",
            "transfer",
            "vehicle_use",
            "exterior",
            "interior",
            "hardware",
        ):
            factor = getattr(suggestion, field_name)
            label = f"{suggestion.case_id}/{field_name}"
            if "模型调用失败" in factor.reason:
                reasons.append(f"{label}模型调用失败")
            if (
                not factor.evidence_sufficient
                and factor.suggested_index != 100
            ):
                reasons.append(f"{label}证据不足但指数不为100")
            if factor.evidence_sufficient and (
                factor.confidence < minimum_confidence
            ):
                reasons.append(
                    f"{label}置信度{factor.confidence:.0%}低于"
                    f"{minimum_confidence:.0%}"
                )
            if abs(factor.grade_difference) > maximum_grade_difference:
                reasons.append(
                    f"{label}档位差{factor.grade_difference}超过自动范围"
                )
    return AdjustmentReviewDecision(
        requires_review=bool(reasons),
        reasons=list(dict.fromkeys(reasons)),
    )
