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
        indices.inspection_index,
        indices.annual_mileage_index,
        indices.registration_date_index,
        indices.transfer_index,
        indices.vehicle_use_index,
        indices.exterior_index,
        indices.interior_index,
        indices.engine_transmission_index,
        indices.chassis_index,
        indices.electrical_index,
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


def calculate_price_from_index_values(
    price_cny: Decimal,
    index_values: list[int],
) -> Decimal:
    """根据一组条件指数计算案例修正后价格。"""

    adjusted_price = price_cny

    for index_value in index_values:
        if index_value <= 0:
            raise ValueError(
                "条件指数必须大于0"
            )

        adjusted_price *= (
            BASE_INDEX
            / Decimal(index_value)
        )

    return adjusted_price


def calculate_rounded_average_value(
    adjusted_prices: list[Decimal],
) -> Decimal:
    """计算平均修正价格并向下取整到百元。"""

    if not adjusted_prices:
        raise ValueError(
            "至少需要一个修正后价格"
        )

    average_price = (
        sum(adjusted_prices, Decimal("0"))
        / Decimal(len(adjusted_prices))
    )

    return (
        average_price // Decimal("100")
    ) * Decimal("100")