from copy import deepcopy
from datetime import date
from decimal import Decimal
from unittest.mock import Mock
import pytest
from sqlalchemy import select
from backend.agent.procurement import ProcurementAgent
from backend.demo import dataset, run_request
from backend.domain.engine import amount, round_order
from backend.domain.schemas import LineEdit, Resolution, Review
from backend.models.entities import POLine, PODraft, SKUCheckResult, ToolExecutionLog
from backend.tools.procurement import ProcurementTools
from backend.tools.runtime import BusinessError


def review(draft):
    return Review(expected_version=draft["version"], comment="Human verified quantities and commercial evidence", confirm=True)


def first(t, run):
    return next(r for r in t.get_all_skus(run) if r["sku_id"] == "SKU-001")


def codes(t, run):
    return {e["code"] for e in t.list_exceptions(run) if e["status"] == "OPEN"}


def test_all_active_skus_receive_exactly_one_state(t, start, data):
    data["sku_master"][9]["active"] = False
    run = start(data)
    summary = t.get_run_summary(run)
    assert summary["expected_sku_count"] == summary["processed_count"] == 9
    results = t.get_all_skus(run)
    assert len({r["sku_id"] for r in results}) == 9
    assert all(r["status"] in {"REORDER", "NO_REORDER", "BLOCKED"} for r in results)


def test_missing_inventory_blocked_other_skus_continue(t, start, data):
    data["inventory_snapshot"].pop(0)
    run = start(data)
    assert first(t, run)["status"] == "BLOCKED"
    assert "MISSING_INVENTORY" in codes(t, run)
    assert t.get_run_summary(run)["processed_count"] == 10
    assert len(t.generate_po_drafts(run)) == 3


@pytest.mark.parametrize("conflict, expected", [(False, "DUPLICATE_INVENTORY"), (True, "CONFLICTING_INVENTORY")])
def test_duplicate_inventory(t, start, data, conflict, expected):
    row = deepcopy(data["inventory_snapshot"][0])
    if conflict:
        row["on_hand"] = 999
    data["inventory_snapshot"].append(row)
    run = start(data)
    assert expected in codes(t, run)
    assert first(t, run)["status"] == "BLOCKED"


def test_late_po_does_not_cover_earlier_demand(t, start, data):
    data["open_po"] = [dict(sku_id="SKU-001", po_number="LATE", quantity=500, arrival_date="2026-10-05", status="OPEN")]
    run = start(data)
    result = first(t, run)
    assert result["valid_incoming"] == 0
    assert result["projected_stock"] == -20
    assert result["final_order_qty"] == 80
    assert "LATE_OPEN_PO" in codes(t, run)


def test_on_time_po_and_multiple_demands_not_double_counted(t, start, data):
    data["open_po"] = [dict(sku_id="SKU-001", po_number="EARLY", quantity=50, arrival_date="2026-09-29", status="OPEN")]
    data["demand"].append(dict(sku_id="SKU-001", quantity=50, need_date="2026-10-02"))
    run = start(data)
    result = first(t, run)
    assert result["projected_stock"] == -20
    assert result["valid_incoming"] == 50
    assert result["demand_qty"] == 80


@pytest.mark.parametrize("raw, moq, pack, expected", [(36, 50, 10, 50), (63, 50, 10, 70), (2, 51, 10, 60), (1, 0, 1, 1)])
def test_moq_pack_business_uat(raw, moq, pack, expected):
    assert round_order(raw, moq, pack) == expected


@pytest.mark.parametrize("field,value,code", [
    ("unit_price", "TEAM TO DEFINE", "MISSING_PRICE"),
    ("unit_price", "NaN", "MISSING_PRICE"),
    ("unit_price", -1, "MISSING_PRICE"),
    ("moq", "unknown", "INVALID_MOQ"),
    ("pack_multiple", 0, "INVALID_PACK_MULTIPLE"),
    ("approved_for_sku", False, "SUPPLIER_NOT_APPROVED"),
    ("currency", None, "CURRENCY_MISMATCH"),
    ("updated_at", "2025-01-01", "STALE_DATA"),
])
def test_bad_commercial_data_blocks(t, start, data, field, value, code):
    data["supplier_sku"][0][field] = value
    run = start(data)
    assert first(t, run)["status"] == "BLOCKED"
    assert code in codes(t, run)


def test_supplier_master_approval_enforced(t, start, data):
    data["supplier_master"][0]["approved"] = False
    run = start(data)
    assert first(t, run)["status"] == "BLOCKED"
    assert "SUPPLIER_NOT_APPROVED" in codes(t, run)


def test_missing_mapping(t, start, data):
    data["supplier_sku"].pop(0)
    run = start(data)
    assert "MISSING_SUPPLIER_MAPPING" in codes(t, run)


def test_stale_inventory(t, start, data):
    data["inventory_snapshot"][0]["snapshot_date"] = "2026-09-01"
    run = start(data)
    assert first(t, run)["status"] == "BLOCKED"
    assert "STALE_DATA" in codes(t, run)


def test_no_reorder_needs_no_commercial_values(t, start, data):
    data["inventory_snapshot"][0]["on_hand"] = 100
    data["supplier_sku"].pop(0)
    run = start(data)
    assert first(t, run)["status"] == "NO_REORDER"


def test_grouped_and_idempotent_generation(t, start):
    run = start()
    drafts = t.generate_po_drafts(run)
    assert len(drafts) == 3
    assert sum(len(d["lines"]) for d in drafts) == 9
    assert all(len(d["lines"]) == 3 for d in drafts)
    assert t.generate_po_drafts(run) == drafts
    assert all(line["result_id"] for d in drafts for line in d["lines"])


@pytest.mark.parametrize("field,value", [("quantity", 100), ("unit_price", "4.5000")])
def test_approval_invalidated_after_critical_edit(t, start, field, value):
    draft = t.generate_po_drafts(start())[0]
    approved = t.approve_po(draft["id"], review(draft))
    assert "PRE_TAX" in t.export_po(draft["id"])["content"]
    edited = t.update_po_line(draft["id"], draft["lines"][0]["id"],
        LineEdit(expected_version=approved["version"], reason="Human correction", **{field: value}))
    assert edited["status"] == "NEEDS_REVIEW"
    assert edited["reviewer"] is None and edited["approved_at"] is None
    with pytest.raises(BusinessError, match="Only explicitly"):
        t.export_po(draft["id"])
    t.approve_po(draft["id"], review(edited))


def test_stale_version_and_bad_quantity_rejected(t, start):
    draft = t.generate_po_drafts(start())[0]
    with pytest.raises(BusinessError, match="MOQ"):
        t.update_po_line(draft["id"], draft["lines"][0]["id"], LineEdit(expected_version=draft["version"], quantity=51, reason="Correction"))
    t.approve_po(draft["id"], review(draft))
    with pytest.raises(BusinessError, match="refresh"):
        t.reject_po(draft["id"], review(draft))


def test_machine_cannot_approve(db, t, start):
    draft = t.generate_po_drafts(start())[0]
    machine = ProcurementTools(db)
    with pytest.raises(BusinessError, match="human"):
        machine.approve_po(draft["id"], review(draft))
    assert t.get_po_draft(draft["id"])["status"] != "APPROVED"


def test_amount_mismatch_blocks_approval(db, t, start):
    draft = t.generate_po_drafts(start())[0]
    line = db.get(POLine, draft["lines"][0]["id"])
    line.amount += Decimal("1.00")
    db.commit()
    with pytest.raises(BusinessError) as exc:
        t.approve_po(draft["id"], review(draft))
    assert exc.value.code == "PO_AMOUNT_MISMATCH"


def test_total_mismatch_blocks_approval(db, t, start):
    draft = t.generate_po_drafts(start())[0]
    db.get(PODraft, draft["id"]).total += Decimal("1.00")
    db.commit()
    with pytest.raises(BusinessError) as exc:
        t.approve_po(draft["id"], review(draft))
    assert exc.value.code == "PO_AMOUNT_MISMATCH"


def test_resolution_reruns_affected_sku_and_retains_evidence(t, start, data):
    data["supplier_sku"][0]["unit_price"] = None
    run = start(data)
    result = first(t, run)
    exc = next(e for e in t.list_exceptions(run) if e["code"] == "MISSING_PRICE")
    context = deepcopy(result["context"])
    context["commercial"][0]["unit_price"] = "2.50"
    fixed = t.resolve_exception(exc["id"], Resolution(expected_revision=result["revision"], context=context, reason="Synthetic price confirmed"))
    assert fixed["status"] == "REORDER" and fixed["revision"] == result["revision"] + 1
    summary = t.get_run_summary(run)
    assert summary["processed_count"] == 10 and summary["blocked_count"] == 0
    history = next(e for e in t.list_exceptions(run) if e["id"] == exc["id"])
    assert history["status"] == "RESOLVED"
    assert history["resolved_value"]["before"]["commercial"][0]["unit_price"] is None


def test_false_resolution_not_accepted(t, start, data):
    data["inventory_snapshot"].pop(0)
    run = start(data)
    result = first(t, run)
    exc = next(e for e in t.list_exceptions(run) if e["code"] == "MISSING_INVENTORY")
    with pytest.raises(BusinessError, match="does not resolve"):
        t.resolve_exception(exc["id"], Resolution(expected_revision=result["revision"], context=result["context"], reason="No change"))


def test_rerun_invalidates_approved_source(t, start):
    run = start()
    draft = t.generate_po_drafts(run)[0]
    t.approve_po(draft["id"], review(draft))
    t.rerun_sku(run, draft["lines"][0]["sku_id"])
    assert t.get_po_draft(draft["id"])["status"] == "NEEDS_REVIEW"
    generated = t.generate_po_drafts(run)
    assert len(generated) == 3 and sum(len(d["lines"]) for d in generated) == 9


def test_failed_tool_is_logged_and_not_fake_success(db, t):
    with pytest.raises(BusinessError):
        t.generate_po_drafts("nonexistent")
    logs = list(db.scalars(select(ToolExecutionLog)))
    assert len(logs) == 1 and logs[0].status == "FAILED" and logs[0].output is None
    fake = Mock()
    fake.create_procurement_run.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="unavailable"):
        ProcurementAgent(fake).daily_review(run_request("x", date(2026, 9, 27)))
    fake.generate_po_drafts.assert_not_called()


def test_demo_agent_report(t):
    batch = t.import_dataset(dataset(date(2026, 9, 27)))
    report = ProcurementAgent(t).daily_review(run_request(batch["id"], date(2026, 9, 27)))
    assert report["run"]["processed_count"] == 10
    assert report["run"]["blocked_count"] == 3
    assert report["run"]["reorder_count"] == 6
    assert report["run"]["no_reorder_count"] == 1
    assert report["next_action"] == "RESOLVE_EXCEPTIONS_AND_REVIEW"
    assert all(d["status"] != "APPROVED" for d in report["drafts"])


def test_agent_resumes_from_approved_state(t, start):
    run = start()
    for draft in t.generate_po_drafts(run):
        t.approve_po(draft["id"], review(draft))
    assert ProcurementAgent(t).resume(run)["next_action"] == "APPROVED_READY_FOR_EXPORT"


def test_audit_listing_does_not_recursively_embed_itself(t):
    t.list_resources("audit")
    logs = t.list_resources("audit")
    assert logs[0]["output"] == {"count": 0, "ids": []}


def test_decimal_money():
    assert amount(3, Decimal("0.3350")) == Decimal("1.01")


def test_run_input_is_frozen(db, t, start):
    run = start()
    result = first(t, run)
    assert db.get(SKUCheckResult, result["id"]).context == result["context"]
    t.import_dataset(dataset(date(2026, 10, 1)))
    assert first(t, run)["context"] == result["context"]
