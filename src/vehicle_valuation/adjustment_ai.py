from vehicle_valuation.adjustment_rules import (
    AdjustmentRuleSet,
    calculate_grade_index,
    map_market_condition_grade,
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
    subject_grade: str,
    comparable_grade: str | None,
    grades: list[str],
    points_per_grade: int,
    factor_label: str,
    condition_summary: str | None,
) -> None:
    """使用平台综合车况和规则计算一个车况指数。"""

    if comparable_grade is None:
        suggestion.grade_difference = 0
        suggestion.suggested_index = 100
        suggestion.direction = "insufficient"
        suggestion.evidence_sufficient = False
        suggestion.confidence = min(
            suggestion.confidence,
            0.5,
        )
        suggestion.reason = (
            "市场案例没有可映射的综合车况，"
            "因此不作调整。"
        )
        return

    subject_position = grades.index(
        subject_grade
    )
    comparable_position = grades.index(
        comparable_grade
    )

    difference = (
        comparable_position
        - subject_position
    )

    suggestion.grade_difference = difference
    suggestion.suggested_index = (
        calculate_grade_index(
            subject_grade=subject_grade,
            comparable_grade=comparable_grade,
            grades=grades,
            points_per_grade=points_per_grade,
        )
    )

    if difference > 0:
        suggestion.direction = "case_better"
    elif difference < 0:
        suggestion.direction = "case_worse"
    else:
        suggestion.direction = "same"

    suggestion.evidence_sufficient = True
    suggestion.confidence = 0.6
    suggestion.reason = (
        f"瓜子仅提供综合车况“{condition_summary}”，"
        f"暂时映射为“{comparable_grade}”，"
        f"作为{factor_label}的代理等级。"
        f"待估车辆为“{subject_grade}”，"
        f"相差{abs(difference)}档，"
        f"每档调整{points_per_grade}分。"
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
    )

    result = provider.generate(
        prompt,
        AIComparisonSuggestion,
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

    comparable_grade = (
        map_market_condition_grade(
            detail.condition_summary
        )
    )

    apply_condition_rule(
        suggestion=result.exterior,
        subject_grade=(
            request.inspection.exterior_grade
        ),
        comparable_grade=comparable_grade,
        grades=rules.condition_grades,
        points_per_grade=(
            rules.condition_rules.exterior.points_per_grade
        ),
        factor_label="外观",
        condition_summary=detail.condition_summary,
    )

    apply_condition_rule(
        suggestion=result.interior,
        subject_grade=(
            request.inspection.interior_grade
        ),
        comparable_grade=comparable_grade,
        grades=rules.condition_grades,
        points_per_grade=(
            rules.condition_rules.interior.points_per_grade
        ),
        factor_label="内饰",
        condition_summary=detail.condition_summary,
    )

    apply_condition_rule(
        suggestion=result.hardware,
        subject_grade=(
            request.inspection.hardware_grade
        ),
        comparable_grade=comparable_grade,
        grades=rules.condition_grades,
        points_per_grade=(
            rules.condition_rules.hardware.points_per_grade
        ),
        factor_label="硬件",
        condition_summary=detail.condition_summary,
    )

    return result
