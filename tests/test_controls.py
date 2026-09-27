from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import os
from sqlalchemy.orm import Session
import pytest
from backend.domain.schemas import Resolution, Review
from backend.tools.procurement import ProcurementTools


def test_human_supplier_correction_invalidates_old_po(t, start):
    run = start()
    drafts = t.generate_po_drafts(run)
    old = next(d for d in drafts if d["supplier_id"] == "SUP-A")
    t.approve_po(old["id"], Review(expected_version=old["version"], comment="Reviewed", confirm=True))
    result = t.get_sku_context(run, "SKU-001")
    context = deepcopy(result["context"])
    context["commercial"][0]["supplier_id"] = "SUP-B"
    t.update_sku_context(run, "SKU-001", Resolution(expected_revision=result["revision"], reason="Human corrected default supplier", context=context))
    assert t.get_po_draft(old["id"])["status"] == "NEEDS_REVIEW"
    drafts = t.generate_po_drafts(run)
    assert len(drafts) == 3
    assert not any(line["sku_id"] == "SKU-001" for d in drafts if d["supplier_id"] == "SUP-A" for line in d["lines"])
    assert any(line["sku_id"] == "SKU-001" for d in drafts if d["supplier_id"] == "SUP-B" for line in d["lines"])


def test_open_po_after_horizon_excluded(t, start, data):
    data["open_po"] = [dict(sku_id="SKU-001", po_number="FUTURE", quantity=1000, arrival_date="2027-01-01", status="OPEN")]
    run = start(data)
    assert t.get_sku_context(run, "SKU-001")["valid_incoming"] == 0


def test_overdue_po_requires_confirmation(t, start, data):
    data["open_po"] = [dict(sku_id="SKU-001", po_number="OVERDUE", quantity=1000, arrival_date="2026-09-20", status="OPEN")]
    run = start(data)
    assert t.get_sku_context(run, "SKU-001")["status"] == "BLOCKED"
    assert any(e["code"] == "OVERDUE_OPEN_PO" for e in t.list_exceptions(run))


def test_incoming_on_need_date_counts(t, start, data):
    data["open_po"] = [dict(sku_id="SKU-001", po_number="ONTIME", quantity=100, arrival_date="2026-09-30", status="OPEN")]
    run = start(data)
    assert t.get_sku_context(run, "SKU-001")["status"] == "NO_REORDER"


def test_cancelled_po_does_not_count(t, start, data):
    data["open_po"] = [dict(sku_id="SKU-001", po_number="CANCELLED", quantity=100, arrival_date="2026-09-30", status="CANCELLED")]
    run = start(data)
    assert t.get_sku_context(run, "SKU-001")["status"] == "REORDER"


def test_failed_correction_rolls_back_source_and_po(t, start):
    run = start()
    result = t.get_sku_context(run, "SKU-001")
    context = deepcopy(result["context"])
    context["sku"]["active"] = False
    from backend.tools.runtime import BusinessError
    with pytest.raises(BusinessError):
        t.update_sku_context(run, "SKU-001", Resolution(expected_revision=result["revision"], reason="Invalid deactivate", context=context))
    assert t.get_sku_context(run, "SKU-001") == result


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL row-lock integration test")
def test_concurrent_generation_single_draft_per_supplier(db, t, start):
    run = start()
    engine = db.get_bind()
    def generate():
        with Session(engine) as session:
            return ProcurementTools(session).generate_po_drafts(run)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: generate(), range(2)))
    assert {d["id"] for d in responses[0]} == {d["id"] for d in responses[1]}
    assert sum(len(d["lines"]) for d in t.generate_po_drafts(run)) == 9
