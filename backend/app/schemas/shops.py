"""Shop API models. No model ever carries the FBR token or its ciphertext."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Shop
from app.schemas.shop_allowance import AllowanceSummaryOut
from app.services.shops import ShopCounts, format_rate, token_status


class ShopOut(BaseModel):
    id: uuid.UUID
    name: str
    branch_name: str
    code: str
    pos_id: str
    status: Literal["active", "inactive"]
    fbr_token_status: Literal["configured", "not_configured", "unreadable"]
    fbr_token_updated_at: datetime | None
    # Exact text ("18.00"); null = not configured (cannot take new uploads).
    sales_tax_rate: str | None
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, s: Shop) -> "ShopOut":
        return cls(
            id=s.id,
            name=s.name,
            branch_name=s.branch_name,
            code=s.code,
            pos_id=s.pos_id,
            status="active" if s.is_active else "inactive",
            fbr_token_status=token_status(s),  # type: ignore[arg-type]
            fbr_token_updated_at=s.fbr_token_updated_at,
            sales_tax_rate=format_rate(s.sales_tax_rate),
            version=s.version,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )


class ShopSummaryOut(BaseModel):
    total: int
    active: int
    inactive: int

    @classmethod
    def from_counts(cls, c: ShopCounts) -> "ShopSummaryOut":
        return cls(total=c.total, active=c.active, inactive=c.inactive)


class ShopPageOut(BaseModel):
    items: list[ShopOut]
    total: int
    limit: int
    offset: int
    summary: ShopSummaryOut
    allowance: AllowanceSummaryOut


class CreateShopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=400)
    branch_name: str = Field(min_length=1, max_length=400)
    code: str = Field(min_length=1, max_length=100)
    pos_id: str = Field(min_length=1, max_length=100)
    # Optional: needs the "Manage FBR token" permission when provided.
    fbr_token: str | None = Field(default=None, max_length=4096)
    # Required: exact decimal text, e.g. "18" or "17.5" (validated by the service).
    sales_tax_rate: str | None = Field(default=None, max_length=12)


class UpdateShopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=400)
    branch_name: str | None = Field(default=None, min_length=1, max_length=400)
    code: str | None = Field(default=None, min_length=1, max_length=100)
    pos_id: str | None = Field(default=None, min_length=1, max_length=100)
    sales_tax_rate: str | None = Field(default=None, max_length=12)


class ShopVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class SetFbrTokenRequest(ShopVersionRequest):
    fbr_token: str = Field(min_length=1, max_length=4096)
