from datetime import date
from decimal import Decimal

from typing import Literal, Self
from pydantic import BaseModel, Field, model_validator


class SubjectVehicle(BaseModel):
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

    valuation_date: date

    @model_validator(mode="after")
    def validate_book_values(self) -> Self:
        if self.book_value_net_cny > self.book_value_original_cny:
            raise ValueError("账面净值不能大于账面原值")
        return self
    