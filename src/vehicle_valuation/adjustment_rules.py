import json
from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, model_validator


class GradeRule(BaseModel):
    """表示一个车况因素每相差一档的调整分值。"""

    points_per_grade: int = Field(gt=0)


class AnnualMileageRule(BaseModel):
    """表示年均里程的分档规则。"""

    upper_bounds_km: list[int] = Field(min_length=1)
    points_per_grade: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        """确保里程边界按从小到大排列。"""

        if self.upper_bounds_km != sorted(
            self.upper_bounds_km
        ):
            raise ValueError(
                "里程边界必须从小到大排列"
            )

        return self


class RegistrationRule(BaseModel):
    """表示上牌时间的分档规则。"""

    years_per_grade: int = Field(gt=0)
    points_per_grade: int = Field(gt=0)


class ConditionRules(BaseModel):
    """表示三项车况因素的调整规则。"""

    exterior: GradeRule
    interior: GradeRule
    hardware: GradeRule


class AdjustmentRuleSet(BaseModel):
    """表示一次车辆评估使用的完整调整规则。"""

    rule_set_id: str = Field(min_length=1)
    rule_name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    case_specific: bool

    condition_grades: list[str] = Field(
        min_length=2
    )
    condition_rules: ConditionRules
    annual_mileage_rule: AnnualMileageRule
    registration_rule: RegistrationRule


def load_adjustment_rule_set(
    path: Path,
) -> AdjustmentRuleSet:
    """读取并校验调整规则JSON文件。"""

    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    return AdjustmentRuleSet.model_validate(data)


def calculate_grade_index(
    subject_grade: str,
    comparable_grade: str,
    grades: list[str],
    points_per_grade: int,
) -> int:
    """根据待估车辆与案例的档次差计算指数。"""

    try:
        subject_position = grades.index(
            subject_grade
        )
        comparable_position = grades.index(
            comparable_grade
        )
    except ValueError as error:
        raise ValueError(
            "车辆状况档次不在规则列表中"
        ) from error

    grade_difference = (
        comparable_position
        - subject_position
    )

    return (
        100
        + grade_difference
        * points_per_grade
    )


def map_market_condition_grade(
    condition_summary: str | None,
) -> str | None:
    """把市场平台的综合车况映射为五档等级。"""

    if condition_summary is None:
        return None

    mappings = [
        ("优秀", "好"),
        ("良好", "较好"),
        ("一般", "一般"),
        ("较差", "较差"),
        ("差", "差"),
    ]

    for keyword, grade in mappings:
        if keyword in condition_summary:
            return grade

    return None


def find_annual_mileage_level(
    annual_mileage_km: float,
    upper_bounds_km: list[int],
) -> int:
    """根据年均里程找到对应档次，里程越低档次越高。"""

    for index, upper_bound in enumerate(
        upper_bounds_km
    ):
        if annual_mileage_km <= upper_bound:
            return (
                len(upper_bounds_km)
                - index
            )

    return 0


def calculate_annual_mileage_bucket_index(
    subject_annual_mileage_km: float,
    comparable_annual_mileage_km: float,
    rule: AnnualMileageRule,
) -> int:
    """根据年均里程档次差计算案例指数。"""

    subject_level = find_annual_mileage_level(
        subject_annual_mileage_km,
        rule.upper_bounds_km,
    )

    comparable_level = find_annual_mileage_level(
        comparable_annual_mileage_km,
        rule.upper_bounds_km,
    )

    level_difference = (
        comparable_level
        - subject_level
    )

    return (
        100
        + level_difference
        * rule.points_per_grade
    )


def calculate_registration_year_index(
    subject_year: int,
    comparable_year: int,
    rule: RegistrationRule,
) -> int:
    """根据上牌年份档次差计算案例指数。"""

    year_difference = (
        comparable_year
        - subject_year
    )

    if year_difference >= 0:
        level_difference = (
            year_difference
            // rule.years_per_grade
        )
    else:
        level_difference = -(
            abs(year_difference)
            // rule.years_per_grade
        )

    return (
        100
        + level_difference
        * rule.points_per_grade
    )