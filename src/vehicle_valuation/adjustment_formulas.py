from datetime import date
from decimal import Decimal, ROUND_HALF_UP


BASE_INDEX = Decimal("100")
ANNUAL_MILEAGE_STEP_KM = Decimal("600")
REGISTRATION_STEP_YEARS = Decimal("0.2")
DAYS_PER_YEAR = Decimal("365")


def excel_round(
    value: Decimal,
    decimal_places: int = 0,
) -> Decimal:
    """按照Excel的方式对Decimal数值进行四舍五入。"""

    unit = Decimal("1").scaleb(-decimal_places)

    return value.quantize(
        unit,
        rounding=ROUND_HALF_UP,
    )


def calculate_used_years(
    valuation_date: date,
    registration_date: date,
) -> Decimal:
    """根据评估基准日和上牌日期计算已使用年限。"""

    used_days = (
        valuation_date - registration_date
    ).days

    if used_days <= 0:
        raise ValueError(
            "评估基准日必须晚于上牌日期"
        )

    return excel_round(
        Decimal(used_days) / DAYS_PER_YEAR,
        decimal_places=2,
    )


def calculate_annual_mileage(
    mileage_km: int,
    used_years: Decimal,
) -> Decimal:
    """使用累计里程除以已使用年限计算年均里程。"""

    if used_years <= 0:
        raise ValueError("已使用年限必须大于0")

    return excel_round(
        Decimal(mileage_km) / used_years
    )


def calculate_annual_mileage_index(
    subject_annual_mileage: Decimal,
    comparable_annual_mileage: Decimal,
) -> Decimal:
    """按照每600公里调整1点计算案例年均里程指数。"""

    index = (
        BASE_INDEX
        + (
            subject_annual_mileage
            - comparable_annual_mileage
        )
        / ANNUAL_MILEAGE_STEP_KM
    )

    return excel_round(index)


def calculate_registration_date_index(
    subject_registration_date: date,
    comparable_registration_date: date,
) -> Decimal:
    """按照每0.2年调整1点计算案例上牌时间指数。"""

    difference_days = (
        comparable_registration_date
        - subject_registration_date
    ).days

    index = (
        BASE_INDEX
        + Decimal(difference_days)
        / DAYS_PER_YEAR
        / REGISTRATION_STEP_YEARS
    )

    return excel_round(index)