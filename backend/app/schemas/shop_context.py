"""Shop context API models. Options carry only ID, name and code: never a POS ID,
FBR token, ciphertext, branch or status details."""

import uuid
from typing import Literal

from pydantic import BaseModel

from app.services.shop_context import ShopContext, ShopOption


class ShopOptionOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str

    @classmethod
    def from_option(cls, o: ShopOption) -> "ShopOptionOut":
        return cls(id=o.id, name=o.name, code=o.code)


SelectionStatus = Literal["all", "active", "inactive", "not_found", "invalid"]


class SelectionOut(BaseModel):
    """How the backend judged the shop the browser asked about.

    Anything but "all"/"active" means: fall back to All Shops and tell the user.
    """

    status: SelectionStatus
    shop: ShopOptionOut | None  # set only for "active"


class ShopAccessInfoOut(BaseModel):
    """How wide this account's shop scope is (no shop details)."""

    mode: Literal["company", "all", "selected", "none"]
    all_label: str  # "All Shops" (Company Admin) or "All Assigned Shops"


class ShopOptionsOut(BaseModel):
    items: list[ShopOptionOut]  # active shops in the account's scope, by name then code
    total: int
    truncated: bool
    selection: SelectionOut
    access: ShopAccessInfoOut


class ShopContextOut(BaseModel):
    scope: Literal["all", "shop"]
    shop: ShopOptionOut | None

    @classmethod
    def from_context(cls, c: ShopContext) -> "ShopContextOut":
        return cls(
            scope="all" if c.shop is None else "shop",
            shop=ShopOptionOut.from_option(c.shop) if c.shop else None,
        )
