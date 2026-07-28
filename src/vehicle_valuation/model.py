from datetime import date
from decimal import Decimal
from typing import Literal, Self
from pydantic import BaseModel, Field, HttpUrl, model_validator


ConditionGrade = Literal["差", "较差", "一般", "较好", "好"]

class SubjectVehicle(BaseModel):
    sequence_number: int = Field(gt=0)
    asset_id: str = Field(min_length=1)
    plate_number: str = Field(min_length=1)
    vehicle_name: str = Field(min_length=1)
    manufacturer: str = Field(min_length=1)

    unit: Literal["辆"]
    quantity: int = Field(gt=0)

    purchase_date: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    in_service_date: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    mileage_km: int = Field(ge=0)
    book_value_original_cny: Decimal = Field(ge=0)
    book_value_net_cny: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_book_values(self) -> Self:
        if self.book_value_net_cny > self.book_value_original_cny:
            raise ValueError("账面净值不能大于账面原值")
        return self
    

class ComparableVehicle(BaseModel):
    case_id: str = Field(min_length=1)

    source_name: str = Field(min_length=1)
    source_url: HttpUrl
    contact: str = Field(min_length=1)

    vehicle_model: str = Field(min_length=1)
    registration_date: str = Field(
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$"
    )
    mileage_km: int = Field(ge=0)

    exterior_condition: str = Field(min_length=1)
    interior_condition: str = Field(min_length=1)
    hardware_condition: str = Field(min_length=1)

    price_cny: Decimal = Field(gt=0)
    price_type: Literal["挂牌价", "询价", "成交价"]
    tax_included: bool
    notes: str = ""


class ComparisonIndices(BaseModel):
    case_id: str = Field(min_length=1)

    transaction_index: Decimal = Field(gt=0)
    transaction_date_index: Decimal = Field(gt=0)

    exterior_index: Decimal = Field(gt=0)
    interior_index: Decimal = Field(gt=0)
    hardware_index: Decimal = Field(gt=0)

    annual_mileage_index: Decimal = Field(gt=0)
    used_years_index: Decimal = Field(gt=0)

    reason: str = Field(min_length=1)
    confirmed_by_user: bool = False


class VehicleInspection(BaseModel):
    inspection_date: date
    actual_mileage_km: int = Field(ge=0)

    exterior_grade: ConditionGrade
    interior_grade: ConditionGrade
    hardware_grade: ConditionGrade

    can_start: bool
    can_drive: bool

    notes: str = ""


class DrivingLicenseData(BaseModel):
    plate_number: str = Field(min_length=1)
    vehicle_type: str = Field(min_length=1)
    owner_name: str = Field(min_length=1)
    address: str = Field(min_length=1)
    use_character: str = Field(min_length=1)
    vehicle_model: str = Field(min_length=1)
    vin: str = Field(min_length=1)
    engine_number: str = Field(min_length=1)
    registration_date: date
    issue_date: date


class ValuationRequest(BaseModel):
    valuation_date: date

    subject_vehicle: SubjectVehicle
    driving_license: DrivingLicenseData
    inspection: VehicleInspection


class ValuationCalculationRequest(BaseModel):
    """表示用户确认市场案例和比较指数后的计算输入。"""

    initial_request: ValuationRequest

    comparables: list[ComparableVehicle] = Field(
        min_length=3
    )
    comparison_indices: list[ComparisonIndices] = Field(
        min_length=3
    )

    @model_validator(mode="after")
    def validate_case_ids(self) -> Self:
        """检查市场案例与比较指数的案例编号是否唯一且一致。"""

        comparable_ids = [
            case.case_id
            for case in self.comparables
        ]
        index_ids = [
            indices.case_id
            for indices in self.comparison_indices
        ]

        if len(comparable_ids) != len(set(comparable_ids)):
            raise ValueError("市场案例中存在重复的case_id")

        if len(index_ids) != len(set(index_ids)):
            raise ValueError("比较指数中存在重复的case_id")

        if set(comparable_ids) != set(index_ids):
            raise ValueError(
                "市场案例与比较指数的case_id不一致"
            )

        return self