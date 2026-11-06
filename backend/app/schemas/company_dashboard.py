"""Company dashboard response. Counts only; no account details, no secrets."""

from typing import Literal

from pydantic import BaseModel

from app.schemas.shop_allowance import AllowanceSummaryOut
from app.schemas.shop_context import ShopContextOut
from app.services.company_dashboard import CompanyDashboard, Metric

METRIC_SCOPES: dict[str, Literal["company", "context"]] = {
    "total_shops": "company",
    "active_shops": "company",
    "active_users": "company",
    "shop_allowance": "company",
    "pending_approvals": "context",
    "pending_fbr_sync": "context",
    "sales_overview": "context",
    "recent_uploads": "context",
}


class MetricOut(BaseModel):
    """``available=false`` means the module does not exist yet: ``value`` is null,
    not zero. A genuine zero is ``available=true, value=0``."""

    available: bool
    value: int | None
    unavailable_reason: str | None

    @classmethod
    def from_metric(cls, metric: Metric) -> "MetricOut":
        return cls(
            available=metric.available,
            value=metric.value,
            unavailable_reason=metric.unavailable_reason,
        )


class SectionStatusOut(BaseModel):
    available: Literal[False]
    unavailable_reason: str


class CompanyDashboardOut(BaseModel):
    company: dict[Literal["name"], str | None]
    metrics: dict[
        Literal[
            "total_shops", "active_shops", "active_users", "pending_approvals", "pending_fbr_sync"
        ],
        MetricOut,
    ]
    sales_overview: SectionStatusOut
    recent_uploads: SectionStatusOut
    shop_allowance: AllowanceSummaryOut
    # The shop context this response was built for (All Shops or one shop).
    context: ShopContextOut
    # "company": always company-wide (administrative), never filtered by shop.
    # "context": follows the selected shop context once the module exists.
    metric_scopes: dict[str, Literal["company", "context"]]

    @classmethod
    def from_data(
        cls, data: CompanyDashboard, context: ShopContextOut | None = None
    ) -> "CompanyDashboardOut":
        unavailable = SectionStatusOut(available=False, unavailable_reason=data.uploads_reason)
        return cls(
            company={"name": data.company_name},
            metrics={
                "total_shops": MetricOut.from_metric(data.total_shops),
                "active_shops": MetricOut.from_metric(data.active_shops),
                "active_users": MetricOut.from_metric(data.active_users),
                "pending_approvals": MetricOut.from_metric(data.pending_approvals),
                "pending_fbr_sync": MetricOut.from_metric(data.pending_fbr_sync),
            },
            sales_overview=unavailable,
            recent_uploads=unavailable,
            shop_allowance=AllowanceSummaryOut.from_usage(data.shop_allowance),
            context=context or ShopContextOut(scope="all", shop=None),
            metric_scopes=METRIC_SCOPES,
        )
