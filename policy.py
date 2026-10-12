"""Layer 2 (design-level) defense: the decision comes from code, not from the document.

The model's job shrinks to *extracting* facts (vendor, SKU, price, lead time,
minimum order). This module then applies the handbook's four purchasing checks
deterministically, using the approved list, the removed/pending list, and the
catalogue's max unit costs parsed straight from data/shop_handbook.md. Nothing a
vendor writes can change these rules or the arithmetic.

It also gates the two dangerous tools: send_email and approve_payment only ever
log, and they refuse unless a human authorization exists. No authorization
channel is reachable by the model, and none is granted in this homework.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from models import PurchasingChecks, VendorDecision

HANDBOOK = Path(__file__).resolve().parent / "data" / "shop_handbook.md"
MAX_LEAD_DAYS = 21
MAX_MIN_ORDER = 600


def _norm(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _section(text: str, number: int) -> str:
    m = re.search(rf"^## {number}\..*?(?=^## \d+\.|\Z)", text, re.M | re.S)
    return m.group(0) if m else ""


def _rows(section: str) -> list[list[str]]:
    rows = []
    for line in section.splitlines():
        if line.startswith("|") and not re.match(r"^\|\s*-", line):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows[1:]  # drop the header row


@lru_cache(maxsize=1)
def handbook_tables() -> dict:
    text = HANDBOOK.read_text(encoding="utf-8")
    approved = {_norm(r[1]): r[1] for r in _rows(_section(text, 5))}
    removed = {_norm(r[0]): r[0] for r in _rows(_section(text, 6))}
    catalogue = {}
    for r in _rows(_section(text, 9)):
        catalogue[r[0].upper()] = float(r[4].replace("$", "").replace(",", ""))
    return {"approved": approved, "removed": removed, "catalogue": catalogue}


def decide(extracted: VendorDecision) -> tuple[VendorDecision, list[str]]:
    """Recompute checks, decision and reason from the extracted facts.

    Returns the corrected decision and a list of what was changed versus the
    model's own answer (empty if the model already agreed).
    """
    t = handbook_tables()
    vendor = _norm(extracted.vendor_name)
    sku = (extracted.sku or "").upper().strip()
    max_cost = t["catalogue"].get(sku)

    if not vendor:
        approved = "unknown"
    elif vendor in t["removed"]:
        approved = "fail"
    elif vendor in t["approved"]:
        approved = "pass"
    else:
        approved = "fail"   # not on the approved list = not approved

    price = ("unknown" if extracted.unit_price is None or max_cost is None
             else "pass" if extracted.unit_price <= max_cost else "fail")
    lead = ("unknown" if extracted.lead_time_days is None
            else "pass" if extracted.lead_time_days <= MAX_LEAD_DAYS else "fail")
    moq = ("unknown" if extracted.min_order_units is None
           else "pass" if extracted.min_order_units <= MAX_MIN_ORDER else "fail")
    checks = PurchasingChecks(approved_vendor=approved, price=price, lead_time=lead, min_order=moq)
    decision = "recommend" if all(c == "pass" for c in (approved, price, lead, moq)) else "do_not_recommend"

    if decision == "recommend":
        reason = "Recommend: approved vendor, price, lead time and minimum order all pass."
    elif approved == "fail":
        where = "on the removed/pending list" if vendor in t["removed"] else "not on the approved vendor list"
        reason = f"Do not recommend: approved vendor check fails because {extracted.vendor_name} is {where}."
    elif approved == "unknown":
        reason = "Do not recommend: approved vendor check is unknown because the document does not name the vendor."
    elif price == "fail":
        reason = (f"Do not recommend: price check fails because ${extracted.unit_price:.2f} is above the "
                  f"${max_cost:.2f} max unit cost.")
    elif price == "unknown":
        reason = ("Do not recommend: price check is unknown because "
                  + ("the document does not state a unit price." if extracted.unit_price is None
                     else f"{sku or 'the SKU'} is not in the catalogue."))
    elif lead == "fail":
        reason = f"Do not recommend: lead time check fails because {extracted.lead_time_days} days is over the 21-day limit."
    elif lead == "unknown":
        reason = "Do not recommend: lead time check is unknown because the document does not state a lead time."
    elif moq == "fail":
        reason = f"Do not recommend: minimum order check fails because {extracted.min_order_units} units is over the 600-unit limit."
    else:
        reason = "Do not recommend: minimum order check is unknown because the document does not state a minimum order."

    final = extracted.model_copy(update={
        "catalogue_max_unit_cost": max_cost, "checks": checks, "decision": decision, "reason": reason,
    })
    changed = []
    if extracted.catalogue_max_unit_cost != max_cost:
        changed.append(f"catalogue_max_unit_cost {extracted.catalogue_max_unit_cost} -> {max_cost}")
    if extracted.checks != checks:
        changed.append(f"checks {extracted.checks.model_dump()} -> {checks.model_dump()}")
    if extracted.decision != decision:
        changed.append(f"decision {extracted.decision} -> {decision}")
    return final, changed


# --- dangerous-tool gate ----------------------------------------------------------

# A real deployment would set this only from a trusted, human-facing channel
# (e.g. an owner clicking Approve in a UI). Nothing the model or a document says
# can set it, and this homework never sets it.
HUMAN_AUTHORIZATION: dict | None = None


def authorized(tool: str, arguments: dict) -> bool:
    """True only if a human pre-approved exactly this call. Always False here."""
    return bool(HUMAN_AUTHORIZATION and HUMAN_AUTHORIZATION.get(tool) == arguments)
