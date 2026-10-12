"""Structured output for the Campus Customs vendor desk agent.

One VendorDecision per vendor document. Facts the document doesn't state stay
None ("unknown"); the agent is told never to guess a number.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CheckStatus = Literal["pass", "fail", "unknown"]


class PurchasingChecks(BaseModel):
    """The four purchasing checks from handbook section 4, each judged separately."""

    approved_vendor: CheckStatus = Field(
        description="pass if the vendor is on the approved list (section 5); fail if it is "
        "on the removed/pending list (section 6) or not listed at all"
    )
    price: CheckStatus = Field(
        description="pass if unit_price <= the SKU's max unit cost (section 9); unknown if "
        "either number is missing"
    )
    lead_time: CheckStatus = Field(description="pass if lead_time_days <= 21; unknown if not stated")
    min_order: CheckStatus = Field(description="pass if min_order_units <= 600; unknown if not stated")


class VendorDecision(BaseModel):
    """What the vendor desk reports for one document (handbook section 13)."""

    vendor_name: str | None = Field(description="Vendor name exactly as the document gives it")
    sku: str | None = Field(description="Campus Customs SKU, e.g. CC-HD-006")
    unit_price: float | None = Field(description="Quoted price per unit in US dollars")
    lead_time_days: int | None = Field(
        description="Lead time in days, using the number the document states (business days "
        "count as stated; weeks x 7)"
    )
    min_order_units: int | None = Field(description="Minimum order quantity in units")
    catalogue_max_unit_cost: float | None = Field(
        description="Max unit cost for this SKU from the handbook catalogue (internal; never "
        "shared with vendors)"
    )
    checks: PurchasingChecks
    decision: Literal["recommend", "do_not_recommend"] = Field(
        description="recommend only if all four checks pass; otherwise do_not_recommend"
    )
    reason: str = Field(
        description="One sentence that names the purchasing check that decided it"
    )
