import csv
import io
import json
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile
import pytest
from fastapi.testclient import TestClient
from backend.config import settings
from backend.db.session import get_session
from backend.demo import run_request
from backend.main import app


@pytest.fixture
def client(db):
    def override():
        yield db
    app.dependency_overrides[get_session] = override
    with TestClient(app, raise_server_exceptions=False) as c:
        c.headers["X-API-Key"] = settings().api_key
        yield c
    app.dependency_overrides.clear()


def csv_files(data):
    from backend.domain.schemas import Dataset
    files = []
    for table, rows in data.items():
        buffer = io.StringIO()
        fields = list(Dataset.model_fields[table].annotation.__args__[0].model_fields)
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        files.append(("files", (f"{table}.csv", buffer.getvalue().encode(), "text/csv")))
    return files


def xlsx_bytes(data):
    """Minimal standards-based test fixture, built in memory (not a delivered workbook)."""
    from backend.domain.schemas import Dataset
    buffer = io.BytesIO()
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package = "http://schemas.openxmlformats.org/package/2006/relationships"
    with ZipFile(buffer, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, 7)) + '</Types>')
        z.writestr("_rels/.rels", f'<Relationships xmlns="{package}"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>' + ''.join(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(data, 1)) + '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{package}">' + ''.join(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, 7)) + '</Relationships>')
        for i, (table, records) in enumerate(data.items(), 1):
            fields = list(Dataset.model_fields[table].annotation.__args__[0].model_fields)
            rows = [fields] + [[r.get(k, "") for k in fields] for r in records]
            z.writestr(f"xl/worksheets/sheet{i}.xml", f'<worksheet xmlns="{ns}"><sheetData>' + ''.join('<row>' + ''.join(f'<c t="inlineStr"><is><t>{escape(str(v))}</t></is></c>' for v in row) + '</row>' for row in rows) + '</sheetData></worksheet>')
    return buffer.getvalue()


@pytest.mark.parametrize("kind", ["json", "csv", "xlsx"])
def test_http_end_to_end(client, data, kind):
    if kind == "json":
        response = client.post("/api/v1/imports", json=data)
    elif kind == "csv":
        response = client.post("/api/v1/imports/upload", files=csv_files(data))
    else:
        response = client.post("/api/v1/imports/upload", files=[("files", ("data.xlsx", xlsx_bytes(data), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))])
    assert response.status_code == 201, response.text
    batch = response.json()["data"]
    assert batch["status"] == "VALIDATED", batch
    request = run_request(batch["id"], date(2026, 9, 27)).model_dump(mode="json")
    response = client.post("/api/v1/agent/review", json=request)
    assert response.status_code == 200, response.text
    report = response.json()["data"]
    assert report["run"]["processed_count"] == 10
    draft = report["drafts"][0]
    body = {"expected_version": draft["version"], "confirm": True, "comment": "Human checked PO"}
    assert client.post(f'/api/v1/drafts/{draft["id"]}/approve', json=body).status_code == 403
    assert client.get(f'/api/v1/drafts/{draft["id"]}/export').status_code == 409
    client.headers["X-API-Key"] = settings().reviewer_api_key
    assert client.post(f'/api/v1/drafts/{draft["id"]}/approve', json=body).status_code == 200
    exported = client.get(f'/api/v1/drafts/{draft["id"]}/export')
    assert exported.status_code == 200
    assert "text/csv" in exported.headers["content-type"]
    assert "SYNTHETIC-WH-1" in exported.text
    history = client.get(f'/api/v1/drafts/{draft["id"]}/history').json()["data"]
    assert {h["action"] for h in history} >= {"APPROVED", "EXPORTED"}


def test_http_error_shapes(client):
    assert client.get("/health").status_code == 200
    assert client.post("/api/v1/runs", json={}).json()["error"]["code"] == "VALIDATION_ERROR"
    missing = client.get("/api/v1/runs/missing")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"
    client.headers.pop("X-API-Key")
    assert client.get("/api/v1/runs").status_code == 401


def test_rejected_import_cannot_run(client, data):
    data["sku_master"].append(data["sku_master"][0])
    batch = client.post("/api/v1/imports", json=data).json()["data"]
    assert batch["status"] == "REJECTED"
    request = run_request(batch["id"], date(2026, 9, 27)).model_dump(mode="json")
    assert client.post("/api/v1/runs", json=request).status_code == 409


def test_original_business_templates_are_normalized(client, data):
    files = csv_files(data)
    root = Path(__file__).resolve().parents[1] / "biz module"
    files = [f for f in files if f[1][0] not in {"supplier_master.csv", "supplier_sku.csv"}]
    for name in ("supplier_master_template.csv", "sku_supplier_map_template.csv"):
        files.append(("files", (name, (root / name).read_bytes(), "text/csv")))
    response = client.post("/api/v1/imports/upload", files=files)
    batch = response.json()["data"]
    assert batch["status"] == "VALIDATED_WITH_ISSUES", batch
    assert any(issue["field"] == "lead_time_days" for issue in batch["issues"])
    request = run_request(batch["id"], date(2026, 9, 27)).model_dump(mode="json")
    report = client.post("/api/v1/agent/review", json=request).json()["data"]
    assert report["run"]["blocked_count"] == 9
    assert not report["drafts"]


def test_upload_unknown_type_rejected(client):
    response = client.post("/api/v1/imports/upload", files=[("files", ("bad.exe", b"x", "application/octet-stream"))])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_UPLOAD"


def test_malformed_workbook_is_validation_error(client):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("unrelated.txt", "Not a workbook")
    response = client.post("/api/v1/imports/upload", files=[("files", ("bad.xlsx", buffer.getvalue(), "application/octet-stream"))])
    assert response.status_code == 422


def test_unknown_sku_and_missing_table_rejected(client, data):
    data["inventory_snapshot"][0]["sku_id"] = "UNKNOWN"
    assert client.post("/api/v1/imports", json=data).json()["data"]["status"] == "REJECTED"
    del data["open_po"]
    assert client.post("/api/v1/imports", json=data).json()["data"]["status"] == "REJECTED"


def test_openapi_is_serializable(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert len(json.loads(response.text)["paths"]) >= 24
