from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.db.session import get_session
from backend.main import app
from backend.models.entities import DemoAccount, DemoSession


def demo_client(db):
    def database():
        yield db

    app.dependency_overrides[get_session] = database
    return TestClient(app)


def test_demo_registration_login_and_workspace_isolation(db):
    client = demo_client(db)
    credentials = {"username": "Demo_Buyer", "password": "safe-demo-password"}
    try:
        registered = client.post("/api/v1/auth/demo/register", json=credentials)
        assert registered.status_code == 201, registered.text
        session = registered.json()["data"]
        assert session["access_token"].startswith("demo_")
        assert session["user"]["name"] == "Demo_Buyer"
        assert session["user"]["email"] == ""

        account = db.scalar(select(DemoAccount).where(DemoAccount.username == "demo_buyer"))
        assert account is not None
        assert credentials["password"] not in account.password_hash
        stored_session = db.scalar(select(DemoSession).where(DemoSession.account_id == account.id))
        assert stored_session is not None
        assert session["access_token"] not in stored_session.token_hash

        headers = {"Authorization": f"Bearer {session['access_token']}"}
        assert client.get("/api/v1/workspaces", headers=headers).json()["data"] == []
        created = client.post("/api/v1/workspaces", headers=headers, json={
            "organization_name": "Demo Organization",
            "name": "Demo Workspace",
            "business_entity": "Demo Entity",
            "warehouse": "DEMO-WH",
            "currency": "SGD",
            "finance_threshold": "5000",
        })
        assert created.status_code == 201, created.text
        listed = client.get("/api/v1/workspaces", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["data"][0]["role"] == "owner"

        logged_in = client.post("/api/v1/auth/demo/login", json={
            "username": "demo_buyer",
            "password": credentials["password"],
        })
        assert logged_in.status_code == 200
        login_token = logged_in.json()["data"]["access_token"]
        assert login_token != session["access_token"]
        login_headers = {"Authorization": f"Bearer {login_token}"}
        assert client.delete("/api/v1/auth/demo/session", headers=login_headers).status_code == 200
        assert client.get("/api/v1/workspaces", headers=login_headers).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_demo_auth_rejects_duplicates_and_wrong_password(db):
    client = demo_client(db)
    try:
        body = {"username": "unique.demo", "password": "safe-demo-password"}
        assert client.post("/api/v1/auth/demo/register", json=body).status_code == 201
        duplicate = client.post("/api/v1/auth/demo/register", json={**body, "username": "UNIQUE.demo"})
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "USERNAME_TAKEN"
        invalid = client.post("/api/v1/auth/demo/login", json={**body, "password": "wrong-password"})
        assert invalid.status_code == 401
        assert invalid.json()["error"]["code"] == "INVALID_CREDENTIALS"
    finally:
        app.dependency_overrides.clear()
