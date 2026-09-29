from pydantic import BaseModel, Field

from .model import DrivingLicenseData, SubjectVehicle, ValuationRequest


class MaterialConflict(BaseModel):
    """跨来源资料冲突，供界面明确展示并阻断后续流程。"""

    field_name: str
    source_values: dict[str, str] = Field(min_length=2)
    possible_ocr_error: bool = False
    message: str


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


def run_structured_checks(
    request: ValuationRequest,
) -> list[MaterialConflict]:
    """逐字段比较 Excel、行驶证 OCR 确认值和现场核查值。"""

    conflicts = run_license_subject_checks(
        request.subject_vehicle,
        request.driving_license,
    )

    if (
        request.subject_vehicle.mileage_km
        != request.inspection.actual_mileage_km
    ):
        conflicts.append(
            MaterialConflict(
                field_name="行驶里程",
                source_values={
                    "Excel": str(request.subject_vehicle.mileage_km),
                    "现场核查": str(request.inspection.actual_mileage_km),
                },
                possible_ocr_error=False,
                message="Excel 账载里程与现场核查里程不一致",
            )
        )

    return conflicts


def run_license_subject_checks(
    subject_vehicle: SubjectVehicle,
    driving_license: DrivingLicenseData,
) -> list[MaterialConflict]:
    """OCR 完成后立即比较 Excel 与行驶证，不等待现场核查提交。"""

    conflicts: list[MaterialConflict] = []
    excel_plate = normalize_plate_number(subject_vehicle.plate_number)
    license_plate = normalize_plate_number(driving_license.plate_number)
    if excel_plate != license_plate:
        conflicts.append(MaterialConflict(
            field_name="车牌号",
            source_values={
                "Excel": subject_vehicle.plate_number,
                "行驶证/OCR": driving_license.plate_number,
            },
            possible_ocr_error=True,
            message="Excel 与行驶证的车牌号不一致",
        ))

    excel_model = normalize_vehicle_model(subject_vehicle.vehicle_name)
    license_model = normalize_vehicle_model(driving_license.vehicle_model)
    if license_model not in excel_model:
        conflicts.append(MaterialConflict(
            field_name="车辆型号",
            source_values={
                "Excel": subject_vehicle.vehicle_name,
                "行驶证/OCR": driving_license.vehicle_model,
            },
            possible_ocr_error=True,
            message="Excel 与行驶证的车辆型号可能不一致",
        ))

    license_month = driving_license.registration_date.strftime("%Y-%m")
    if subject_vehicle.in_service_date != license_month:
        conflicts.append(MaterialConflict(
            field_name="注册年月",
            source_values={
                "Excel": subject_vehicle.in_service_date,
                "行驶证/OCR": license_month,
            },
            possible_ocr_error=True,
            message="Excel 启用年月与行驶证注册年月不一致",
        ))

    if subject_vehicle.vin and (
        subject_vehicle.vin.upper() != driving_license.vin.upper()
    ):
        conflicts.append(MaterialConflict(
            field_name="VIN",
            source_values={
                "Excel": subject_vehicle.vin,
                "行驶证/OCR": driving_license.vin,
            },
            possible_ocr_error=True,
            message="Excel 与行驶证的 VIN 不一致",
        ))
    return conflicts
