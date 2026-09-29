from vehicle_valuation.adjustment_review import evaluate_adjustment_review
from vehicle_valuation.model import AIComparisonSuggestion


def _factor(
    *,
    evidence: bool = False,
    confidence: float = 0.4,
    difference: int = 0,
    index: int = 100,
    reason: str = "证据不足，因此不调整",
) -> dict:
    return {
        "direction": "same" if evidence else "insufficient",
        "grade_difference": difference,
        "suggested_index": index,
        "reason": reason,
        "confidence": confidence,
        "evidence_sufficient": evidence,
    }


def _suggestion(**override) -> AIComparisonSuggestion:
    payload = {
        "case_id": "CASE-1",
        "transaction": _factor(),
        "inspection": _factor(),
        "transfer": _factor(),
        "vehicle_use": _factor(),
        "exterior": _factor(evidence=True, confidence=0.8),
        "interior": _factor(evidence=True, confidence=0.8),
        "hardware": _factor(evidence=True, confidence=0.8),
    }
    payload.update(override)
    return AIComparisonSuggestion.model_validate(payload)


def test_safe_neutral_insufficient_evidence_does_not_require_review() -> None:
    decision = evaluate_adjustment_review([_suggestion()])

    assert decision.requires_review is False


def test_low_confidence_non_neutral_suggestion_requires_review() -> None:
    suggestion = _suggestion(
        exterior=_factor(
            evidence=True,
            confidence=0.5,
            difference=1,
            index=103,
        )
    )

    decision = evaluate_adjustment_review([suggestion])

    assert decision.requires_review is True
    assert any("置信度" in reason for reason in decision.reasons)


def test_model_failure_requires_review() -> None:
    suggestion = _suggestion(
        exterior=_factor(reason="模型调用失败，未生成无依据参数")
    )

    decision = evaluate_adjustment_review([suggestion])

    assert decision.requires_review is True
