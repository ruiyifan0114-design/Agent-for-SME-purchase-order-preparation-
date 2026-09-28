from datetime import date
from decimal import Decimal

import pytest

from backend.demo import run_request
from backend.domain.schemas import LineEdit, Review
from backend.models.entities import PODraft
from backend.tools.procurement import ProcurementTools
from backend.tools.runtime import BusinessError


def review(draft):
    return Review(expected_version=draft["version"], comment="Reviewed evidence", confirm=True)


def sgd_draft(t, data, price):
    sku = data["sku_master"][0]
    sku.update(target_stock=100, safety_stock=20)
    data["sku_master"] = [sku]
    for table in ("supplier_sku", "inventory_snapshot", "demand"):
        data[table] = [data[table][0]]
    data["supplier_sku"][0].update(currency="SGD", unit_price=price)
    data["supplier_master"][0]["currency"] = "SGD"
    data["inventory_snapshot"][0]["on_hand"] = 30
    data["open_po"] = []
    batch = t.import_dataset(data)
    policy = run_request(batch["id"], date(2026, 9, 27)).model_copy(update={"currency": "SGD"})
    run = t.create_procurement_run(policy)
    t.run_full_check(run["id"])
    return t.generate_po_drafts(run["id"])[0]


@pytest.mark.parametrize("price,finance_required", [("49.9999", False), ("50", True), ("50.0001", True)])
def test_threshold_and_two_stage_export(db, t, data, price, finance_required):
    draft = sgd_draft(t, data, price)
    assert draft["requires_finance_review"] == finance_required
    finance = ProcurementTools(db, actor="Finance Manager", human=True, role="finance")
    with pytest.raises(BusinessError):
        finance.finance_approve_po(draft["id"], review(draft))
    approved = t.approve_po(draft["id"], review(draft))
    if finance_required:
        assert approved["status"] == "FINANCE_REVIEW"
        with pytest.raises(BusinessError):
            t.export_po(draft["id"])
        with pytest.raises(BusinessError):
            t.finance_approve_po(draft["id"], review(approved))
        approved = finance.finance_approve_po(draft["id"], review(approved))
        assert approved["finance_reviewer"] == "Finance Manager"
    assert approved["status"] == "APPROVED"
    assert "finance_reviewer" in t.export_po(draft["id"])["content"]


def test_critical_edit_clears_both_approvals(db, t, data):
    draft = sgd_draft(t, data, "50")
    draft = t.approve_po(draft["id"], review(draft))
    finance = ProcurementTools(db, actor="Finance Manager", human=True, role="finance")
    draft = finance.finance_approve_po(draft["id"], review(draft))
    updated = t.update_po_line(draft["id"], draft["lines"][0]["id"], LineEdit(
        expected_version=draft["version"], unit_price=Decimal("51"), reason="Price confirmed"))
    assert updated["status"] == "NEEDS_REVIEW"
    assert updated["reviewer"] is None and updated["finance_reviewer"] is None
    with pytest.raises(BusinessError):
        finance.finance_approve_po(updated["id"], review(updated))


def test_legacy_high_value_approval_cannot_export(db, t, data):
    draft = sgd_draft(t, data, "50")
    t.approve_po(draft["id"], review(draft))
    stored = db.get(PODraft, draft["id"])
    stored.status = "APPROVED"
    db.commit()
    with pytest.raises(BusinessError, match="Finance Manager approval"):
        t.export_po(draft["id"])


def test_finance_can_reject_waiting_draft(db, t, data):
    draft = sgd_draft(t, data, "50")
    draft = t.approve_po(draft["id"], review(draft))
    finance = ProcurementTools(db, actor="Finance Manager", human=True, role="finance")
    rejected = finance.reject_po(draft["id"], review(draft))
    assert rejected["status"] == "REJECTED"
    assert rejected["reviewer"] is None


def test_http_credentials_enforce_separate_approval_roles(db, t, data):
    from fastapi.testclient import TestClient
    from backend.config import settings
    from backend.db.session import get_session
    from backend.main import app

    draft = sgd_draft(t, data, "50")
    def override():
        yield db
    app.dependency_overrides[get_session] = override
    try:
        with TestClient(app) as client:
            payload = review(draft).model_dump()
            purchasing = {"X-API-Key": settings().reviewer_api_key}
            finance = {"X-API-Key": settings().finance_api_key}
            path = f"/api/v1/drafts/{draft['id']}"
            assert client.post(path + "/approve", json=payload, headers=finance).status_code == 403
            response = client.post(path + "/approve", json=payload, headers=purchasing)
            assert response.status_code == 200
            assert response.json()["data"]["status"] == "FINANCE_REVIEW"
            payload = review(response.json()["data"]).model_dump()
            assert client.post(path + "/finance-approve", json=payload, headers=purchasing).status_code == 403
            assert client.post(path + "/finance-approve", json=payload, headers=finance).status_code == 200
    finally:
        app.dependency_overrides.clear()
