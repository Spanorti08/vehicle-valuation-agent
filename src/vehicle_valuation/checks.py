from .model import ValuationRequest


def normalize_plate_number(value: str) -> str:
    return (
        value
        .replace("·", "")
        .replace(" ", "")
        .upper()
    )


def check_plate_number(
    request: ValuationRequest,
) -> str | None:
    excel_plate = normalize_plate_number(
        request.subject_vehicle.plate_number
    )
    license_plate = normalize_plate_number(
        request.driving_license.plate_number
    )

    if excel_plate == license_plate:
        return None

    return (
        "车辆明细与行驶证的车牌号不一致："
        f"Excel={request.subject_vehicle.plate_number}，"
        f"行驶证={request.driving_license.plate_number}"
    )


def normalize_vehicle_model(value: str) -> str:
    """删除车辆型号中的通用描述和无意义标点。"""

    normalized_value = "".join(
        value.split()
    ).upper()

    for generic_word in (
        "小轿车",
        "轿车",
        "汽车",
        "牌",
    ):
        normalized_value = normalized_value.replace(
            generic_word,
            "",
        )

    for symbol in ("-", "·", ".", "/"):
        normalized_value = normalized_value.replace(
            symbol,
            "",
        )

    return normalized_value


def check_vehicle_model(
    request: ValuationRequest,
) -> str | None:
    excel_model = normalize_vehicle_model(
        request.subject_vehicle.vehicle_name
    )
    license_model = normalize_vehicle_model(
        request.driving_license.vehicle_model
    )

    if license_model in excel_model:
        return None

    return (
        "车辆明细与行驶证的车辆型号可能不一致："
        f"Excel={request.subject_vehicle.vehicle_name}，"
        f"行驶证={request.driving_license.vehicle_model}"
    )


def check_registration_month(
    request: ValuationRequest,
) -> str | None:
    excel_month = request.subject_vehicle.in_service_date

    license_month = (
        request.driving_license.registration_date
        .strftime("%Y-%m")
    )

    if excel_month == license_month:
        return None

    return (
        "车辆明细的启用年月与行驶证注册年月不一致："
        f"Excel={excel_month}，"
        f"行驶证={license_month}"
    )


def run_initial_checks(
    request: ValuationRequest,
) -> list[str]:
    """运行全部初始资料检查，并返回发现的问题列表。"""

    check_functions = (
        check_plate_number,
        check_vehicle_model,
        check_registration_month,
    )

    issues = []

    for check_function in check_functions:
        result = check_function(request)

        if result is not None:
            issues.append(result)

    return issues