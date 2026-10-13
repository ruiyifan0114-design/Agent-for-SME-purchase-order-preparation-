from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from backend.advanced_demo import scenario
from backend.domain.inventory.engine import inventory_policy
from backend.domain.matching.engine import three_way_match
from backend.domain.pricing.engine import landed_cost
from backend.domain.receiving.engine import apply_receipt, transition_po
from backend.domain.schemas import ApprovalRuleCreate, InvoiceRequest, ReceiptRequest, Review, SourcingRequest
from backend.tools.runtime import BusinessError


def test_return_replacement_uses_net_received_quantity():
    returned = apply_receipt(10, 10, 0, 0, 4)
    assert returned["result"]["open_quantity"] == 4
    replaced = apply_receipt(10, 10, 4, 4, 0)
    assert replaced["result"]["open_quantity"] == 0
    with pytest.raises(ValueError):
        apply_receipt(10, 10, 5, 4, 0)


def test_inventory_policy_is_applied_and_frozen_in_run(t, start):
    from backend.domain.schemas import InventoryPolicyCreate
    t.create_domain_record("inventory-policies", InventoryPolicyCreate(
        sku_id="SKU-001", policy_type="TARGET_STOCK", rule_version=1,
        parameters={"safety_stock": 1000, "target_stock": 2000},
        effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc)))
    run = start()
    original = t.get_sku_context(run, "SKU-001")
    assert original["evidence"]["inventory_policy"]["rule_version"] == 1
    assert original["raw_order_qty"] == 2000 - original["projected_stock"]
    t.create_domain_record("inventory-policies", InventoryPolicyCreate(
        sku_id="SKU-001", policy_type="TARGET_STOCK", rule_version=2,
        parameters={"safety_stock": 0, "target_stock": 0},
        effective_from=datetime(2021, 1, 1, tzinfo=timezone.utc)))
    t.run_full_check(run)
    repeated = t.get_sku_context(run, "SKU-001")
    assert repeated["raw_order_qty"] == original["raw_order_qty"]
    assert repeated["evidence"]["inventory_policy"]["rule_version"] == 1


def test_agreement_price_and_costs_reach_po_without_double_counting(t, start, data):
    from backend.domain.schemas import CommercialAgreementCreate
    mapping = next(item for item in data["supplier_sku"] if item["sku_id"] == "SKU-001")
    t.create_domain_record("commercial-agreements", CommercialAgreementCreate(
        supplier_id=mapping["supplier_id"], sku_id="SKU-001", agreement_number="CONTRACT-1",
        valid_from=date(2026, 1, 1), currency=mapping["currency"],
        terms={"contract_price": "2", "freight_fixed": "12", "additional_cost": "3"}))
    run = start()
    result = t.get_sku_context(run, "SKU-001")
    request = SourcingRequest(required_quantity=result["final_order_qty"], as_of=date(2026, 9, 27),
        offers=[{"supplier_id": mapping["supplier_id"], "approved": True, "unit_price": "9",
                 "moq": mapping["moq"], "pack_multiple": mapping["pack_multiple"], "lead_time_days": 3}])
    t.source_sku(run, "SKU-001", request)
    draft = next(item for item in t.generate_po_drafts(run) if item["supplier_id"] == mapping["supplier_id"])
    line = next(item for item in draft["lines"] if item["sku_id"] == "SKU-001")
    assert Decimal(line["unit_price"]) == 2
    assert Decimal(draft["freight"]) == 15
    assert Decimal(draft["landed_cost"]) == Decimal(draft["total"]) + 15
    t.source_sku(run, "SKU-001", request)
    regenerated = next(item for item in t.generate_po_drafts(run) if item["id"] == draft["id"])
    assert Decimal(regenerated["freight"]) == 15


def test_matching_checks_cumulative_invoicing():
    result = three_way_match(
        {"line_id": "L", "po_number": "PO", "sku_id": "SKU", "quantity": 10,
         "unit_price": "2", "previously_invoiced_quantity": 7},
        [{"po_line_id": "L", "quantity": 10}],
        {"po_number": "PO", "sku_id": "SKU", "quantity": 4, "unit_price": "2"}, {})
    assert result["result"]["exceptions"] == ["QUANTITY_MISMATCH"]
    assert result["intermediate"]["cumulative_invoiced_quantity"] == 11


def test_receipt_status_cannot_be_set_without_receipt(t, start):
    draft = t.generate_po_drafts(start())[0]
    with pytest.raises(BusinessError) as blocked:
        t.transition_po_lifecycle(draft["id"], "RECEIVED", "no receipt")
    assert blocked.value.code == "RECEIPT_REQUIRED"


@pytest.mark.parametrize("name", [
    "supplier-comparison", "split-order", "delayed-supplier", "tier-pricing",
    "safety-stock-reorder-point", "partial-receipt", "three-way-match-exception",
    "approval-escalation",
])
def test_advanced_demo_scenarios_are_deterministic(name):
    assert scenario(name) == scenario(name)


def test_split_order_respects_capacity_and_explains_selection():
    result = scenario("split-order")
    assert len(result["result"]["allocations"]) == 2
    assert sum(row["quantity"] for row in result["result"]["allocations"]) >= 100
    assert result["applied_rule"] == "MIN_LANDED_COST_PLUS_CONFIGURED_RISK_PENALTY"


def test_tier_and_contract_price_boundary():
    offer = {"unit_price": "12", "contract_price": "8", "valid_from": "2026-01-01",
             "valid_to": "2026-12-31", "tiers": [{"minimum_quantity": 100, "unit_price": "9"}]}
    result = landed_cost(offer, 100, date(2026, 12, 31))
    assert result["applied_rule"] == "contract_price"
    assert result["result"]["transaction_total"] == "800.00"
    with pytest.raises(ValueError):
        landed_cost(offer, 100, date(2027, 1, 1))


def test_service_level_policy_and_invalid_holding_cost():
    result = scenario("safety-stock-reorder-point")
    assert result["intermediate"]["safety_stock"] > 0
    assert result["intermediate"]["eoq"] > 0
    policy = {"policy_type": "ROP_EOQ", "average_daily_demand": 1, "lead_time_days": 1,
              "service_level": .95, "annual_demand": 10, "order_cost": 1,
              "annual_holding_cost_per_unit": 0}
    with pytest.raises(ValueError):
        inventory_policy({"on_hand": 0}, policy)


def test_receipt_boundaries_and_lifecycle_conflict():
    assert apply_receipt(100, 0, 40)["result"] == {"open_quantity": 60, "status": "PARTIALLY_RECEIVED"}
    assert apply_receipt(100, 40, 60)["result"]["status"] == "RECEIVED"
    with pytest.raises(ValueError):
        apply_receipt(100, 90, 20)
    with pytest.raises(ValueError):
        transition_po("DRAFT", "RECEIVED")


def test_three_way_matching_exposes_quantity_and_price_conflicts():
    result = scenario("three-way-match-exception")
    assert result["result"]["status"] == "EXCEPTION"
    assert set(result["result"]["exceptions"]) == {"QUANTITY_MISMATCH", "PRICE_MISMATCH"}


def test_approval_matrix_escalates_and_records_delegation():
    steps = scenario("approval-escalation")["result"]["steps"]
    assert [step["required_role"] for step in steps] == ["purchasing", "finance", "admin"]
    assert steps[1]["delegated"] is True
    assert steps[1]["delegation_id"] == "DEL-1"


def test_persisted_partial_receipt_and_match_exception(t, start):
    run = start()
    draft = t.generate_po_drafts(run)[0]
    reviewed = t.approve_po(draft["id"], Review(expected_version=draft["version"], comment="ok", confirm=True))
    if reviewed["status"] == "FINANCE_REVIEW":
        reviewed = t.finance_approve_po(
            draft["id"], Review(expected_version=reviewed["version"], comment="finance ok", confirm=True))
    t.transition_po_lifecycle(draft["id"], "SENT", "Sent to test supplier")
    line = t.get_po_draft(draft["id"])["lines"][0]
    partial = max(1, line["quantity"] // 2)
    receipt = t.record_goods_receipt(draft["id"], ReceiptRequest(
        external_id="GR-TEST-1", received_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
        lines=[{"po_line_id": line["id"], "quantity": partial}],
    ))
    assert receipt["external_id"] == "GR-TEST-1"
    assert t.get_po_draft(draft["id"])["lifecycle_status"] == "PARTIALLY_RECEIVED"
    invoice = t.record_and_match_invoice(draft["id"], InvoiceRequest(
        supplier_id=draft["supplier_id"], invoice_number="INV-TEST-1", invoice_date=date(2026, 9, 29),
        currency=draft["currency"], exchange_rate=Decimal("1"), exchange_rate_date=date(2026, 9, 29),
        exchange_rate_source="test-fixed", lines=[{"po_line_id": line["id"], "sku_id": line["sku_id"],
        "quantity": line["quantity"], "unit_price": Decimal(str(line["unit_price"]))}],
    ))
    assert invoice["status"] == "MATCH_EXCEPTION"


def test_persisted_split_sourcing_generates_supplier_drafts(t, start):
    run = start()
    result = t.get_sku_context(run, "SKU-001")
    quantity = result["final_order_qty"]
    first_capacity = max(10, ((quantity // 2) // 10) * 10)
    offers = [
        {"supplier_id": "SUP-A", "supplier_name": "Supplier A", "approved": True,
         "unit_price": "1", "moq": 10, "pack_multiple": 10,
         "max_quantity": first_capacity, "lead_time_days": 3},
        {"supplier_id": "SUP-SPLIT", "supplier_name": "Split Supplier", "approved": True,
         "unit_price": "1.10", "moq": 10, "pack_multiple": 10,
         "max_quantity": quantity - first_capacity, "lead_time_days": 4},
    ]
    decision = t.source_sku(run, "SKU-001", SourcingRequest(
        required_quantity=quantity, as_of=date(2026, 9, 27), offers=offers, allow_split=True))
    assert len(decision["trace"]["result"]["allocations"]) == 2
    drafts = t.generate_po_drafts(run)
    sourced_lines = [(draft["supplier_id"], line) for draft in drafts for line in draft["lines"]
                     if line["sku_id"] == "SKU-001"]
    assert {supplier for supplier, _ in sourced_lines} == {"SUP-A", "SUP-SPLIT"}
    assert sum(line["quantity"] for _, line in sourced_lines) >= quantity


def test_configured_approval_matrix_is_enforced_and_audited(t, start):
    t.role = "owner"
    t.create_domain_record("approval-rules", ApprovalRuleCreate(
        rule_version=1, sequence=1, conditions={"minimum_amount": "0"},
        required_role="purchasing", effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc)))
    draft = t.generate_po_drafts(start())[0]
    with pytest.raises(BusinessError) as blocked:
        t.approve_po(draft["id"], Review(expected_version=draft["version"], comment="premature", confirm=True))
    assert blocked.value.code == "APPROVAL_MATRIX_REQUIRED"
    approved_step = t.matrix_approve(
        draft["id"], Review(expected_version=draft["version"], comment="matrix reviewed", confirm=True))
    assert approved_step["approved_step"]["required_role"] == "purchasing"
    reviewed = t.approve_po(
        draft["id"], Review(expected_version=draft["version"], comment="final purchasing review", confirm=True))
    assert reviewed["status"] in {"APPROVED", "FINANCE_REVIEW"}
    assert any(event["action"] == "MATRIX_APPROVED" for event in t.approval_history(draft["id"]))


def test_later_approval_rules_do_not_change_historical_run(t, start):
    t.role = "owner"
    run = start()
    t.create_domain_record("approval-rules", ApprovalRuleCreate(
        rule_version=2, sequence=1, conditions={"minimum_amount": "0"},
        required_role="finance", effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc)))
    old_draft = t.generate_po_drafts(run)[0]
    assert t.approval_plan(old_draft["id"])["result"]["steps"] == []
    new_draft = t.generate_po_drafts(start())[0]
    assert t.approval_plan(new_draft["id"])["result"]["steps"][0]["required_role"] == "finance"


def test_modification_invalidates_matrix_approval(t, start):
    from backend.domain.schemas import LineEdit
    t.role = "owner"
    t.create_domain_record("approval-rules", ApprovalRuleCreate(
        rule_version=1, sequence=1, conditions={}, required_role="purchasing",
        effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc)))
    draft = t.generate_po_drafts(start())[0]
    t.matrix_approve(draft["id"], Review(expected_version=draft["version"], comment="reviewed", confirm=True))
    line = draft["lines"][0]
    changed = t.update_po_line(draft["id"], line["id"], LineEdit(
        expected_version=draft["version"], quantity=line["quantity"], reason="Reconfirm quantity"))
    with pytest.raises(BusinessError) as blocked:
        t.approve_po(draft["id"], Review(expected_version=changed["version"], comment="approve", confirm=True))
    assert blocked.value.code == "APPROVAL_MATRIX_REQUIRED"


def test_multi_supplier_mapping_is_resolved_only_by_explicit_sourcing(t, start, data):
    original = next(row for row in data["supplier_sku"] if row["sku_id"] == "SKU-001")
    data["supplier_sku"].append({**original, "supplier_id": "SUP-B", "unit_price": "1.20"})
    run = start(data)
    blocked = t.get_sku_context(run, "SKU-001")
    assert blocked["status"] == "BLOCKED"
    decision = t.source_sku(run, "SKU-001", SourcingRequest(
        required_quantity=blocked["raw_order_qty"], as_of=date(2026, 9, 27), offers=[
            {"supplier_id": "SUP-A", "approved": True, "unit_price": "1", "moq": 10,
             "pack_multiple": 10, "lead_time_days": 3},
            {"supplier_id": "SUP-B", "approved": True, "unit_price": "1.20", "moq": 10,
             "pack_multiple": 10, "lead_time_days": 4},
        ]))
    assert decision["trace"]["result"]["allocations"]
    resolved = t.get_sku_context(run, "SKU-001")
    assert resolved["status"] == "REORDER"
    assert resolved["evidence"]["sourcing_decision_id"] == decision["id"]
