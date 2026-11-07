"""Company dashboard response. Counts only; no account details, no secrets."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, PlainSerializer

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


Money = Annotated[Decimal, PlainSerializer(lambda d: format(d, "f"), return_type=str)]


class SalesOverviewOut(BaseModel):
    """Real totals of saved uploads in the shop context. Every upload is still a
    Draft until the Approval workflow exists, so nothing here is approved or
    sent to FBR (``status_note`` says so)."""

    available: bool
    unavailable_reason: str | None
    uploads: int
    records: int
    total_amount: Money
    total_sales_tax: Money
    total_net_amount: Money
    status_note: str


class RecentUploadOut(BaseModel):
    id: uuid.UUID
    sales_date: date
    shop_name: str
    shop_code: str
    total_records: int
    total_net_amount: Money
    status: str
    uploaded_at: datetime


class RecentUploadsOut(BaseModel):
    available: bool
    unavailable_reason: str | None
    items: list[RecentUploadOut]


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
    sales_overview: SalesOverviewOut
    recent_uploads: RecentUploadsOut
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
        sales = data.sales
        overview = SalesOverviewOut(
            available=sales is not None,
            unavailable_reason=None if sales is not None else data.uploads_reason,
            uploads=sales.uploads if sales else 0,
            records=sales.records if sales else 0,
            total_amount=sales.amount if sales else Decimal("0"),
            total_sales_tax=sales.tax if sales else Decimal("0"),
            total_net_amount=sales.net if sales else Decimal("0"),
            status_note="Draft uploads: not yet approved or sent to FBR.",
        )
        recent = RecentUploadsOut(
            available=data.recent is not None,
            unavailable_reason=None if data.recent is not None else data.uploads_reason,
            items=[
                RecentUploadOut(
                    id=r.batch.id,
                    sales_date=r.batch.sales_date,
                    shop_name=r.shop_name,
                    shop_code=r.shop_code,
                    total_records=r.batch.total_records,
                    total_net_amount=r.batch.total_net_amount,
                    status=r.batch.status,
                    uploaded_at=r.uploaded_at,
                )
                for r in (data.recent or [])
            ],
        )
        return cls(
            company={"name": data.company_name},
            metrics={
                "total_shops": MetricOut.from_metric(data.total_shops),
                "active_shops": MetricOut.from_metric(data.active_shops),
                "active_users": MetricOut.from_metric(data.active_users),
                "pending_approvals": MetricOut.from_metric(data.pending_approvals),
                "pending_fbr_sync": MetricOut.from_metric(data.pending_fbr_sync),
            },
            sales_overview=overview,
            recent_uploads=recent,
            shop_allowance=AllowanceSummaryOut.from_usage(data.shop_allowance),
            context=context or ShopContextOut(scope="all", shop=None),
            metric_scopes=METRIC_SCOPES,
        )
