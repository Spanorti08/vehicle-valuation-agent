from decimal import Decimal

from .model import ComparableVehicle, ComparisonIndices


BASE_INDEX = Decimal("100")


def calculate_adjusted_price(
    comparable: ComparableVehicle,
    indices: ComparisonIndices,
) -> Decimal:
    """根据比较指数计算一辆市场案例的修正后价格。"""

    if comparable.case_id != indices.case_id:
        raise ValueError("市场案例与比较指数的case_id不一致")

    if not indices.confirmed_by_user:
        raise ValueError("比较指数尚未经过人工确认")

    adjusted_price = comparable.price_cny

    comparison_indices = (
        indices.transaction_index,
        indices.transaction_date_index,
        indices.exterior_index,
        indices.interior_index,
        indices.hardware_index,
        indices.annual_mileage_index,
        indices.used_years_index,
    )

    for comparison_index in comparison_indices:
        adjustment_factor = BASE_INDEX / comparison_index
        adjusted_price *= adjustment_factor

    return adjusted_price


def calculate_final_value(
    comparables: list[ComparableVehicle],
    comparison_indices: list[ComparisonIndices],
) -> Decimal:
    """计算全部案例的平均修正价格，并向下取整到百元。"""

    indices_by_case_id = {
        indices.case_id: indices
        for indices in comparison_indices
    }

    adjusted_prices = []

    for comparable in comparables:
        indices = indices_by_case_id[comparable.case_id]

        adjusted_price = calculate_adjusted_price(
            comparable,
            indices,
        )
        adjusted_prices.append(adjusted_price)

    average_price = (
        sum(adjusted_prices, Decimal("0"))
        / Decimal(len(adjusted_prices))
    )

    return (
        average_price // Decimal("100")
    ) * Decimal("100")