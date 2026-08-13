from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self
from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


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


class VehicleModelMapping(BaseModel):
    """表示一条可追溯的法定型号与市场车型映射证据。"""

    mapping_id: str = Field(min_length=1)
    legal_model: str = Field(min_length=1)
    brand: str = Field(min_length=1)

    market_series: str = Field(min_length=1)
    market_keyword: str = Field(min_length=1)
    model_year: str = Field(min_length=1)

    evidence_summary: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    source_url: HttpUrl



class MarketSearchRoute(BaseModel):
    """表示某个市场车系在特定二手车平台的搜索路径。"""

    provider: Literal["guazi"]
    market_series: str = Field(min_length=1)
    series_path: str = Field(min_length=1)


class MarketListing(BaseModel):
    """表示从二手车公开列表页抓取的一条车源。"""

    source_name: str = "瓜子二手车"
    source_url: HttpUrl

    vehicle_model: str = Field(min_length=1)
    registration_year: int = Field(
        ge=1900,
        le=2100,
    )
    mileage_km: int = Field(ge=0)
    city: str = Field(min_length=1)
    price_cny: Decimal = Field(gt=0)
    captured_at: datetime | None = None


class MarketListingDetail(BaseModel):
    """保存从市场案例详情页自动获得的信息。"""

    source_url: HttpUrl

    condition_score: int | None = Field(
        default=None,
        ge=0,
        le=100,
    )
    condition_grade: str | None = None
    condition_summary: str | None = None

    claim_count: int | None = Field(default=None, ge=0)
    transfer_count: int | None = Field(default=None, ge=0)

    inspection_status: str | None = None
    vehicle_use: str | None = None
    body_color: str | None = None

    exterior_condition: str | None = None
    interior_condition: str | None = None
    engine_transmission_condition: str | None = None
    chassis_condition: str | None = None
    electrical_condition: str | None = None


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



ManualAdjustmentFactor = Literal[
    "transaction",
    "inspection",
    "transfer",
    "vehicle_use",
    "exterior",
    "interior",
    "engine_transmission",
    "chassis",
    "electrical",
]


class ManualAdjustmentExample(BaseModel):
    """表示一条经过脱敏和合成的人工参数调整示例。"""

    example_id: str = Field(min_length=1)
    factor: ManualAdjustmentFactor

    subject_condition: str = Field(min_length=1)
    comparable_condition: str = Field(min_length=1)

    suggested_index: int = Field(gt=0)
    decision_reason: str = Field(min_length=1)

    is_synthetic: Literal[True] = True



class ComparisonIndices(BaseModel):
    """表示一个市场案例的全部比较调整指数。"""

    case_id: str = Field(min_length=1)

    transaction_index: Decimal = Field(gt=0)
    inspection_index: Decimal = Field(gt=0)

    annual_mileage_index: Decimal = Field(gt=0)
    registration_date_index: Decimal = Field(gt=0)
    transfer_index: Decimal = Field(gt=0)
    vehicle_use_index: Decimal = Field(gt=0)

    exterior_index: Decimal = Field(gt=0)
    interior_index: Decimal = Field(gt=0)
    engine_transmission_index: Decimal = Field(gt=0)
    chassis_index: Decimal = Field(gt=0)
    electrical_index: Decimal = Field(gt=0)

    reason: str = Field(min_length=1)
    confirmed_by_user: bool = False



class AdjustmentSuggestion(BaseModel):
    """表示 LLM 对一个主观调整因素的建议。"""

    direction: Literal[
        "case_better",
        "same",
        "case_worse",
        "insufficient",
    ]

    grade_difference: int = Field(
        default=0,
        ge=-4,
        le=4,
    )

    suggested_index: int = Field(
        ge=70,
        le=130,
    )
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence_sufficient: bool

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(
        cls,
        value: float,
    ) -> float:
        """把百分制置信度转换为0到1。"""

        numeric_value = float(value)

        if 1 < numeric_value <= 100:
            return numeric_value / 100

        return numeric_value

    @model_validator(mode="after")
    def enforce_direction_consistency(
        self,
    ) -> Self:
        """确保比较方向、证据状态和指数一致。"""

        if (
            not self.evidence_sufficient
            or self.direction == "insufficient"
        ):
            self.suggested_index = 100
            self.confidence = min(
                self.confidence,
                0.5,
            )
            return self

        if self.direction == "same":
            self.suggested_index = 100

        elif (
            self.direction == "case_better"
            and self.suggested_index < 100
        ):
            self.suggested_index = (
                200 - self.suggested_index
            )

        elif (
            self.direction == "case_worse"
            and self.suggested_index > 100
        ):
            self.suggested_index = (
                200 - self.suggested_index
            )

        return self


class AIComparisonSuggestion(BaseModel):
    """表示 LLM 对一个市场案例生成的全部主观参数。"""

    case_id: str = Field(min_length=1)

    transaction: AdjustmentSuggestion
    inspection: AdjustmentSuggestion
    transfer: AdjustmentSuggestion
    vehicle_use: AdjustmentSuggestion

    exterior: AdjustmentSuggestion
    interior: AdjustmentSuggestion
    hardware: AdjustmentSuggestion


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


class GroundedReportSection(BaseModel):
    """保存基于RAG证据生成的报告章节。"""

    section_title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    cited_chunk_ids: list[str] = Field(min_length=1)


class VehicleValuationReportDraft(BaseModel):
    """保存准备写入DOCX的完整车辆评估初稿。"""

    report_title: str = Field(min_length=1)
    declaration: str = Field(min_length=1)
    summary: str = Field(min_length=1)

    client_and_users: str = Field(min_length=1)
    valuation_purpose: str = Field(min_length=1)
    object_and_scope: str = Field(min_length=1)
    value_type: str = Field(min_length=1)
    valuation_date: str = Field(min_length=1)
    valuation_basis: str = Field(min_length=1)
    valuation_method: str = Field(min_length=1)
    valuation_process: str = Field(min_length=1)
    assumptions: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)
    special_matters: str = Field(min_length=1)
    usage_restrictions: str = Field(min_length=1)

    cited_chunk_ids: list[str]
    missing_information: list[str] = []
