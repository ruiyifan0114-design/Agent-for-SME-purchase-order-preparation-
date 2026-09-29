from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api.dependencies import authenticated_user
from backend.db.session import get_session
from backend.main import app
from backend.models.entities import Organization, Workspace
from backend.tools.procurement import ProcurementTools
from backend.tools.runtime import BusinessError


def user(user_id="user-1", email="owner@example.com", actor="Owner"):
    return {
        "actor": actor,
        "email": email,
        "user_id": user_id,
        "human": True,
        "auth_type": "jwt",
    }


def client_for(db, identity):
    def database():
        yield db

    app.dependency_overrides[get_session] = database
    app.dependency_overrides[authenticated_user] = lambda: identity
    return TestClient(app)


def create_workspace(client, suffix="A"):
    response = client.post("/api/v1/workspaces", json={
        "organization_name": f"Organization {suffix}",
        "name": f"Workspace {suffix}",
        "business_entity": f"Entity {suffix}",
        "warehouse": f"Warehouse {suffix}",
        "currency": "SGD",
        "finance_threshold": "5000",
    })
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_workspace_membership_claim_and_role_enforcement(db, data):
    owner_client = client_for(db, user())
    try:
        workspace = create_workspace(owner_client)
        headers = {"X-Workspace-ID": workspace["id"]}
        invite = owner_client.post(f"/api/v1/workspaces/{workspace['id']}/members", headers=headers, json={
            "email": "viewer@example.com", "display_name": "Data Viewer", "role": "viewer",
        })
        assert invite.status_code == 201

        app.dependency_overrides[authenticated_user] = lambda: user("user-2", "viewer@example.com", "Data Viewer")
        listed = owner_client.get("/api/v1/workspaces")
        assert listed.status_code == 200
        assert listed.json()["data"][0]["role"] == "viewer"
        assert owner_client.get("/api/v1/imports", headers=headers).status_code == 200
        assert owner_client.post("/api/v1/imports", headers=headers, json=data).status_code == 403
        assert owner_client.delete("/api/v1/imports/any", headers=headers).status_code == 403
        assert owner_client.delete(f"/api/v1/workspaces/{workspace['id']}", headers=headers).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_resources_cannot_cross_workspace_boundary(db, data):
    first_org = Organization(name="First Org")
    second_org = Organization(name="Second Org")
    db.add_all([first_org, second_org])
    db.flush()
    first = Workspace(org_id=first_org.id, name="First", business_entity="First", warehouse="A")
    second = Workspace(org_id=second_org.id, name="Second", business_entity="Second", warehouse="B")
    db.add_all([first, second])
    db.commit()

    first_tools = ProcurementTools(db, actor="First", human=True, role="owner", workspace_id=first.id)
    batch = first_tools.import_dataset(data)
    second_tools = ProcurementTools(db, actor="Second", human=True, role="owner", workspace_id=second.id)
    assert second_tools.list_resources("imports") == []
    try:
        second_tools.validate_import(batch["id"])
    except BusinessError as exc:
        assert exc.code == "NOT_FOUND"
    else:
        raise AssertionError("Cross-workspace import was visible")


def test_workspace_owns_its_approval_policy(db):
    organization = Organization(name="Threshold Org")
    db.add(organization)
    db.flush()
    workspace = Workspace(
        org_id=organization.id,
        name="US Warehouse",
        business_entity="US Entity",
        warehouse="US-WEST",
        currency="USD",
        finance_threshold=Decimal("1000"),
    )
    db.add(workspace)
    db.commit()
    tools = ProcurementTools(db, actor="Owner", human=True, role="owner", workspace_id=workspace.id)

    assert tools._requires_finance(SimpleNamespace(currency="USD", total=Decimal("1000")))
    assert not tools._requires_finance(SimpleNamespace(currency="SGD", total=Decimal("9000")))


def test_owner_can_delete_empty_workspace_but_not_procurement_history(db, data):
    client = client_for(db, user())
    try:
        empty = create_workspace(client, "Empty")
        headers = {"X-Workspace-ID": empty["id"]}
        removed = client.delete(f"/api/v1/workspaces/{empty['id']}", headers=headers)
        assert removed.status_code == 200
        assert removed.json()["data"]["deleted"] is True

        used = create_workspace(client, "Used")
        headers = {"X-Workspace-ID": used["id"]}
        assert client.post("/api/v1/imports", headers=headers, json=data).status_code == 201
        blocked = client.delete(f"/api/v1/workspaces/{used['id']}", headers=headers)
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "WORKSPACE_IN_USE"
    finally:
        app.dependency_overrides.clear()
