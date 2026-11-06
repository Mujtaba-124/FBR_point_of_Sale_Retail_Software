"""Shop Allowance API models.

Aggregate only: no model here carries a shop ID, name, code, POS ID, branch
or token, so neither workspace can learn shop details through them.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.services.shop_allowance import AllowanceUsage

Mode = Literal["limited", "unlimited"]


class AllowanceSummaryOut(BaseModel):
    """What the Company Workspace sees (Shops page, Dashboard)."""

    mode: Mode
    max_shops: int | None
    registered_shops: int  # active + inactive
    available_slots: int | None  # None when unlimited; never negative
    at_capacity: bool
    over_limit: bool

    @classmethod
    def from_usage(cls, u: AllowanceUsage) -> "AllowanceSummaryOut":
        return cls(
            mode=u.mode,  # type: ignore[arg-type]
            max_shops=u.max_shops,
            registered_shops=u.registered,
            available_slots=u.available,
            at_capacity=u.at_capacity,
            over_limit=u.over_limit,
        )


class ShopAllowanceOut(AllowanceSummaryOut):
    """Super Admin view: the summary plus what the settings form needs."""

    version: int
    last_updated_at: datetime | None

    @classmethod
    def from_usage(cls, u: AllowanceUsage) -> "ShopAllowanceOut":
        base = AllowanceSummaryOut.from_usage(u).model_dump()
        return cls(**base, version=u.version, last_updated_at=u.updated_at)


class ShopAllowanceUpdateOut(BaseModel):
    allowance: ShopAllowanceOut
    changed: bool


class UpdateShopAllowanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode
    # Strict: "5", 5.0, 5.5 and true are rejected, not coerced.
    max_shops: StrictInt | None = None
    expected_version: StrictInt = Field(ge=1)
