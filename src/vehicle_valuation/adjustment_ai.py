from vehicle_valuation.adjustment_rules import (
    AdjustmentRuleSet,
)
from vehicle_valuation.llm_provider import OllamaProvider
from vehicle_valuation.model import (
    AIComparisonSuggestion,
    AdjustmentSuggestion,
    MarketListing,
    MarketListingDetail,
    ValuationRequest,
)


def build_adjustment_prompt(
    case_id: str,
    request: ValuationRequest,
    listing: MarketListing,
    detail: MarketListingDetail,
    rules: AdjustmentRuleSet,
) -> str:
    """把待估车辆和市场案例整理成 LLM提示词。"""

    return f"""
你是车辆市场法评估参数建议助手。

请比较待估车辆与市场案例，生成七项主观调整建议。
外观、内饰和硬件必须填写grade_difference：
案例每好一档填写正数，每差一档填写负数，相同填写0。
最多可以相差4档。

规则：
1. 指数100表示不调整。
2. 案例条件优于待估车辆时，direction填写case_better。
3. 案例条件差于待估车辆时，direction填写case_worse。
4. 没有明确证据时必须返回100。
5. 没有证据时evidence_sufficient=false，不能猜测。
6. confidence必须是0到1的小数。
7. direction只能填写case_better、same、case_worse或insufficient。
8. evidence_sufficient=false时，direction必须填写insufficient。
9. suggested_index只是临时值，最终指数由Python根据规则计算。
10. reason必须引用输入中具体证据，不能只给结论。

当前项目正式规则（只能使用这些规则）：
{rules.model_dump_json()}

案例编号：
{case_id}

待估车辆：
{request.model_dump_json()}

市场案例列表信息：
{listing.model_dump_json()}

市场案例详情：
{detail.model_dump_json()}
""".strip()


def apply_condition_rule(
    suggestion: AdjustmentSuggestion,
    points_per_grade: int,
    factor_label: str,
    factor_evidence: str | None,
) -> None:
    """仅在该因素有证据时，按 LLM 档位差由 Python 计算指数。"""

    if not factor_evidence or not suggestion.evidence_sufficient:
        mark_evidence_insufficient(
            suggestion,
            f"公开页面没有可核验的{factor_label}证据，因此不作调整。",
        )
        return

    difference = suggestion.grade_difference
    suggestion.suggested_index = 100 + difference * points_per_grade
    if difference > 0:
        suggestion.direction = "case_better"
    elif difference < 0:
        suggestion.direction = "case_worse"
    else:
        suggestion.direction = "same"

    suggestion.reason = (
        f"{suggestion.reason}；证据：{factor_evidence}；"
        f"档位差{difference}，每档{points_per_grade}分，"
        "正式指数由 Python 计算。"
    )


def mark_evidence_insufficient(
    suggestion: AdjustmentSuggestion,
    reason: str,
) -> None:
    """证据不足时强制不调整指数，避免模型猜测。"""

    suggestion.grade_difference = 0
    suggestion.suggested_index = 100
    suggestion.direction = "insufficient"
    suggestion.evidence_sufficient = False
    suggestion.confidence = min(
        suggestion.confidence,
        0.5,
    )
    suggestion.reason = reason


def generate_comparison_suggestion(
    provider: OllamaProvider,
    rules: AdjustmentRuleSet,
    case_id: str,
    request: ValuationRequest,
    listing: MarketListing,
    detail: MarketListingDetail,
) -> AIComparisonSuggestion:
    """生成建议并按规则强制计算车况指数。"""

    prompt = build_adjustment_prompt(
        case_id,
        request,
        listing,
        detail,
        rules,
    )

    try:
        result = provider.generate(prompt, AIComparisonSuggestion)
    except Exception as error:
        fallback = AdjustmentSuggestion(
            direction="insufficient",
            grade_difference=0,
            suggested_index=100,
            reason=f"模型调用失败，未生成无依据参数：{error}",
            confidence=0,
            evidence_sufficient=False,
        )
        return AIComparisonSuggestion(
            case_id=case_id,
            transaction=fallback.model_copy(deep=True),
            inspection=fallback.model_copy(deep=True),
            transfer=fallback.model_copy(deep=True),
            vehicle_use=fallback.model_copy(deep=True),
            exterior=fallback.model_copy(deep=True),
            interior=fallback.model_copy(deep=True),
            hardware=fallback.model_copy(deep=True),
        )

    mark_evidence_insufficient(
        result.inspection,
        "公开页面仅说明车辆已检测，未提供可与待估车辆"
        "直接比较的年检或检测结论，因此不作调整。",
    )
    mark_evidence_insufficient(
        result.transfer,
        "当前输入未记录待估车辆过户次数，无法与案例"
        "比较，因此不作调整。",
    )

    if detail.vehicle_use is None:
        mark_evidence_insufficient(
            result.vehicle_use,
            "公开页面未披露案例车辆用途，无法比较，"
            "因此不作调整。",
        )

    apply_condition_rule(
        suggestion=result.exterior,
        points_per_grade=(
            rules.condition_rules.exterior.points_per_grade
        ),
        factor_label="外观",
        factor_evidence=detail.exterior_condition,
    )

    apply_condition_rule(
        suggestion=result.interior,
        points_per_grade=(
            rules.condition_rules.interior.points_per_grade
        ),
        factor_label="内饰",
        factor_evidence=detail.interior_condition,
    )

    apply_condition_rule(
        suggestion=result.hardware,
        points_per_grade=(
            rules.condition_rules.hardware.points_per_grade
        ),
        factor_label="硬件",
        factor_evidence=(
            detail.engine_transmission_condition
            or detail.chassis_condition
            or detail.electrical_condition
        ),
    )

    return result
