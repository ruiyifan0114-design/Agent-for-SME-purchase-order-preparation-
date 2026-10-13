from datetime import date, datetime, timezone

from backend.domain.approval.engine import resolve_approval_steps
from backend.domain.inventory.engine import inventory_policy
from backend.domain.matching.engine import three_way_match
from backend.domain.pricing.engine import landed_cost
from backend.domain.receiving.engine import apply_receipt
from backend.domain.sourcing.engine import rank_suppliers


def _offer(supplier, price, **extra):
    return {"supplier_id": supplier, "approved": True, "unit_price": str(price), "currency": "SGD",
            "moq": 10, "pack_multiple": 10, "lead_time_days": 5,
            "performance": {"on_time_rate": ".95", "lead_time_variance_days": "1",
                            "rejection_rate": ".01", "historical_score": ".9"}, **extra}


def scenario(name: str) -> dict:
    today = date(2026, 9, 27)
    if name == "supplier-comparison":
        offers = [_offer("SUP-A", "10"), _offer("SUP-B", "9.80", freight_fixed="40")]
        return rank_suppliers(100, offers, today)
    if name == "split-order":
        offers = [_offer("SUP-A", "8", max_quantity=60), _offer("SUP-B", "8.50", max_quantity=80)]
        return rank_suppliers(100, offers, today, allow_split=True)
    if name == "delayed-supplier":
        offers = [_offer("SUP-CHEAP-LATE", "7", lead_time_days=30,
                         performance={"on_time_rate": ".55", "lead_time_variance_days": "15",
                                      "rejection_rate": ".05", "historical_score": ".5"}),
                  _offer("SUP-RELIABLE", "8", lead_time_days=4)]
        return rank_suppliers(100, offers, today, {"lead_time": "5", "performance": "500"})
    if name == "tier-pricing":
        return landed_cost(_offer("SUP-TIER", "12", tiers=[
            {"minimum_quantity": 50, "unit_price": "11"},
            {"minimum_quantity": 100, "unit_price": "9.50"}], freight_fixed="25"), 100, today)
    if name == "safety-stock-reorder-point":
        return inventory_policy({"on_hand": 100, "incoming": 0, "demand": 40}, {
            "policy_type": "ROP_EOQ", "average_daily_demand": "12", "lead_time_days": 7,
            "daily_demand_stddev": "4", "service_level": .95, "annual_demand": 4380,
            "order_cost": "30", "annual_holding_cost_per_unit": "2", "stockout_cost": "15",
            "abc_class": "A", "xyz_class": "Y", "rule_version": 2})
    if name == "partial-receipt":
        return apply_receipt(100, 0, 60)
    if name == "three-way-match-exception":
        return three_way_match(
            {"line_id": "LINE-1", "po_number": "PO-1", "sku_id": "SKU-1", "quantity": 100, "unit_price": "10"},
            [{"po_line_id": "LINE-1", "quantity": 80}],
            {"po_number": "PO-1", "sku_id": "SKU-1", "quantity": 100, "unit_price": "11"},
            {"quantity": 0, "price_percent": "2", "rule_version": 1})
    if name == "approval-escalation":
        at = datetime(2026, 9, 27, tzinfo=timezone.utc)
        return resolve_approval_steps(
            {"amount": "12000", "cost_center": "OPS", "supplier_id": "SUP-RISK",
             "risk_level": "HIGH", "rule_version": 3},
            [{"id": "BASE", "sequence": 1, "minimum_amount": 0, "required_role": "purchasing"},
             {"id": "FIN", "sequence": 2, "minimum_amount": 5000, "cost_center": "OPS", "required_role": "finance"},
             {"id": "RISK", "sequence": 3, "minimum_amount": 0, "supplier_id": "SUP-RISK",
              "risk_level": "HIGH", "required_role": "admin"}],
            [{"id": "DEL-1", "delegator_role": "finance", "delegate_role": "finance_delegate",
              "valid_from": "2026-09-01T00:00:00+00:00", "valid_to": "2026-09-30T00:00:00+00:00"}], at)
    raise KeyError(name)
