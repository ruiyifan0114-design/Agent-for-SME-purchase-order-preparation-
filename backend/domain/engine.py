"""Pure deterministic procurement policy; no database, network or language model."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from backend.domain.schemas import Context, RunRequest


def amount(quantity: int, unit_price: Decimal) -> Decimal:
    return (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_order(raw: int, moq: int, pack: int) -> int:
    if raw <= 0 or moq < 0 or pack <= 0:
        raise ValueError("Invalid order modifiers")
    return ((max(raw, moq) + pack - 1) // pack) * pack


def evaluate(context: dict, policy: RunRequest) -> dict:
    c = Context.model_validate(context)
    sku = c.sku
    end = policy.as_of + timedelta(days=policy.horizon)
    out = dict(status="BLOCKED", on_hand=None, valid_incoming=None, demand_qty=None,
               projected_stock=None, raw_order_qty=None, final_order_qty=None,
               decision_reason="Required data missing or conflicting", evidence={}, exceptions=[])

    def issue(code, field, message, severity="BLOCKING"):
        out["exceptions"].append(dict(code=code, required_field=field, message=message,
            severity=severity, source="domain_engine", required_action="Correct source context and rerun affected SKU"))

    def blocked():
        return any(e["severity"] == "BLOCKING" for e in out["exceptions"])

    if not c.inventory:
        issue("MISSING_INVENTORY", "inventory", "No inventory snapshot supplied")
    elif len(c.inventory) != 1:
        code = "DUPLICATE_INVENTORY" if len({(r.on_hand, r.snapshot_date) for r in c.inventory}) == 1 else "CONFLICTING_INVENTORY"
        issue(code, "inventory", "Exactly one inventory snapshot is required per SKU")
    else:
        inv = c.inventory[0]
        out["on_hand"] = inv.on_hand
        if inv.on_hand is None:
            issue("MISSING_INVENTORY", "inventory.on_hand", "Inventory quantity unavailable")
        if inv.snapshot_date is None or not 0 <= (policy.as_of - inv.snapshot_date).days <= policy.inventory_max_age_days:
            issue("STALE_DATA", "inventory.snapshot_date", "Missing, future or stale inventory date")
    if sku.safety_stock is None or sku.target_stock is None or sku.target_stock < sku.safety_stock:
        issue("INVALID_STOCK_POLICY", "sku", "Require target_stock >= safety_stock >= 0")
    if any(d.quantity is None or d.need_date is None for d in c.demand):
        issue("INVALID_DEMAND", "demand", "Demand quantity and need date are required")
    incoming = [p for p in c.open_po if p.status == "OPEN"]
    if any(p.quantity is None or p.arrival_date is None for p in incoming):
        issue("INVALID_OPEN_PO", "open_po", "Open PO quantity and arrival date are required")
    if len({p.po_number for p in c.open_po}) != len(c.open_po):
        issue("DUPLICATE_OPEN_PO", "open_po", "Duplicate open PO number for this SKU")
    if blocked():
        return out
    if any(p.arrival_date < policy.as_of for p in incoming):
        issue("OVERDUE_OPEN_PO", "open_po.arrival_date", "Past-due PO is not confirmed as received; confirm arrival")
        return out
    demands = [d for d in c.demand if d.need_date <= end]  # overdue unfulfilled demand remains due
    checkpoints = sorted({max(d.need_date, policy.as_of) for d in demands} | {end})
    timeline = []
    for day in checkpoints:
        inc = sum(p.quantity for p in incoming if p.arrival_date <= day)
        due = sum(d.quantity for d in demands if d.need_date <= day)
        timeline.append(dict(date=day.isoformat(), valid_incoming=inc, demand_qty=due,
                             projected_stock=out["on_hand"] + inc - due))
    # The binding checkpoint preserves early shortages even if a later PO arrives within the horizon.
    binding = min(timeline, key=lambda t: t["projected_stock"])
    out.update({k: binding[k] for k in ("valid_incoming", "demand_qty", "projected_stock")})
    out["evidence"] = {"timeline": timeline, "binding_date": binding["date"],
                       "horizon_end": end.isoformat(), "policy": "below safety -> replenish to target"}
    for p in incoming:
        if any(d.quantity > 0 and p.arrival_date > d.need_date for d in demands):
            issue("LATE_OPEN_PO", "open_po.arrival_date", f"{p.po_number} cannot cover earlier demand", "WARNING")
    raw = sku.target_stock - out["projected_stock"] if out["projected_stock"] < sku.safety_stock else 0
    out["raw_order_qty"] = raw
    if not raw:
        out.update(status="NO_REORDER", final_order_qty=0, decision_reason="All dated stock checkpoints meet safety stock")
        return out
    if len(c.commercial) != 1 or not c.commercial[0].supplier_id:
        issue("MISSING_SUPPLIER_MAPPING", "commercial", "Require exactly one default supplier mapping")
        return out
    m = c.commercial[0]
    suppliers = [s for s in c.suppliers if s.supplier_id == m.supplier_id]
    if len(suppliers) != 1:
        issue("MISSING_SUPPLIER_MAPPING", "suppliers", "Default supplier not found")
    elif not suppliers[0].approved or not m.approved_for_sku:
        issue("SUPPLIER_NOT_APPROVED", "commercial.approved_for_sku", "Supplier and SKU relation must both be approved")
    if m.currency != policy.currency or (suppliers and suppliers[0].currency != policy.currency):
        issue("CURRENCY_MISMATCH", "commercial.currency", "Supplier, mapping and run must use the same explicit currency")
    if m.unit_price is None:
        issue("MISSING_PRICE", "commercial.unit_price", "Positive unit price required (EX-C03)")
    if m.moq is None:
        issue("INVALID_MOQ", "commercial.moq", "Explicit MOQ required; use 0 when none applies")
    if m.pack_multiple is None:
        issue("INVALID_PACK_MULTIPLE", "commercial.pack_multiple", "Explicit pack multiple required; use 1 for individual units")
    if m.updated_at is None or not 0 <= (policy.as_of - m.updated_at).days <= policy.commercial_max_age_days:
        issue("STALE_DATA", "commercial.updated_at", "Missing, future or stale commercial data (EX-C06)")
    if m.lead_time_days is None:
        issue("MISSING_LEAD_TIME", "commercial.lead_time_days", "Lead time required for feasibility check")
    if blocked():
        return out
    expected = policy.as_of + timedelta(days=m.lead_time_days)
    first_risk = next(t["date"] for t in timeline if t["projected_stock"] < sku.safety_stock)
    if expected > date.fromisoformat(first_risk):
        issue("LEAD_TIME_RISK", "commercial.lead_time_days", "New order may arrive after first safety-stock breach; human review needed", "WARNING")
    final = round_order(raw, m.moq, m.pack_multiple)
    out["evidence"].update(supplier_id=m.supplier_id, unit_price=str(m.unit_price), moq=m.moq,
        pack_multiple=m.pack_multiple, need_date=first_risk, expected_delivery_date=expected.isoformat())
    out.update(status="REORDER", final_order_qty=final,
        decision_reason=f"Projected {out['projected_stock']} < safety {sku.safety_stock}; target {sku.target_stock}; raw {raw}; MOQ {m.moq}; pack {m.pack_multiple}; final {final}")
    return out
