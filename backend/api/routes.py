from typing import Any
from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from backend.agent.procurement import ProcurementAgent
from backend.agent.messages import MessageRequest
from backend.api.dependencies import tools
from backend.domain.intake import MAX_BYTES
from backend.domain.schemas import LineEdit, Resolution, Review, RunRequest
from backend.skills.workflows import Approval, ExceptionResolution
from backend.tools.runtime import BusinessError


class Envelope(BaseModel):
    data: Any


router = APIRouter(prefix="/api/v1")


def ok(data):
    return {"data": data}


@router.post("/imports", response_model=Envelope, status_code=201)
def import_json(dataset: dict, filename: str = Query("dataset.json", min_length=1, max_length=255), t=Depends(tools)):
    return ok(t.import_dataset(dataset, filename))


@router.post("/imports/upload", response_model=Envelope, status_code=201)
async def upload(files: list[UploadFile] = File(...), t=Depends(tools)):
    if len(files) > 6:
        raise BusinessError("Provide at most 6 CSVs or one workbook", "INVALID_UPLOAD", 422)
    inputs, total = [], 0
    for file in files:
        content = await file.read(MAX_BYTES + 1)
        total += len(content)
        if total > MAX_BYTES:
            raise BusinessError("Upload exceeds 10 MiB", "PAYLOAD_TOO_LARGE", 413)
        inputs.append((file.filename or "unknown", content))
    return ok(t.import_files(inputs))


@router.get("/imports", response_model=Envelope)
def imports(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), t=Depends(tools)):
    return ok(t.list_resources("imports", limit, offset))


@router.get("/imports/{batch_id}", response_model=Envelope)
def import_status(batch_id: str, t=Depends(tools)):
    return ok(t.validate_import(batch_id))


@router.post("/runs", response_model=Envelope, status_code=201)
def create_run(request: RunRequest, t=Depends(tools)):
    return ok(t.create_procurement_run(request))


@router.get("/runs", response_model=Envelope)
def runs(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), t=Depends(tools)):
    return ok(t.list_resources("runs", limit, offset))


@router.post("/runs/{run_id}/check", response_model=Envelope)
def check(run_id: str, t=Depends(tools)):
    return ok(t.run_full_check(run_id))


@router.get("/runs/{run_id}", response_model=Envelope)
def summary(run_id: str, t=Depends(tools)):
    return ok(t.get_run_summary(run_id))


@router.get("/runs/{run_id}/results", response_model=Envelope)
def results(run_id: str, t=Depends(tools)):
    return ok(t.get_all_skus(run_id))


@router.get("/runs/{run_id}/skus/{sku_id}", response_model=Envelope)
def context(run_id: str, sku_id: str, t=Depends(tools)):
    return ok(t.get_sku_context(run_id, sku_id))


@router.post("/runs/{run_id}/skus/{sku_id}/rerun", response_model=Envelope)
def rerun(run_id: str, sku_id: str, t=Depends(tools)):
    return ok(t.rerun_sku(run_id, sku_id))


@router.patch("/runs/{run_id}/skus/{sku_id}/context", response_model=Envelope)
def correct_context(run_id: str, sku_id: str, request: Resolution, t=Depends(tools)):
    return ok(t.update_sku_context(run_id, sku_id, request))


@router.get("/runs/{run_id}/exceptions", response_model=Envelope)
def exceptions(run_id: str, t=Depends(tools)):
    return ok(t.list_exceptions(run_id))


@router.post("/exceptions/{exception_id}/resolve", response_model=Envelope)
def resolve(exception_id: str, request: Resolution, t=Depends(tools)):
    return ok(ExceptionResolution(t).execute(exception_id, request))


@router.post("/runs/{run_id}/drafts", response_model=Envelope)
def generate(run_id: str, t=Depends(tools)):
    return ok(t.generate_po_drafts(run_id))


@router.get("/drafts/{draft_id}", response_model=Envelope)
def draft(draft_id: str, t=Depends(tools)):
    return ok(t.get_po_draft(draft_id))


@router.get("/runs/{run_id}/drafts", response_model=Envelope)
def list_drafts(run_id: str, t=Depends(tools)):
    return ok(t.list_po_drafts(run_id))


@router.patch("/drafts/{draft_id}/lines/{line_id}", response_model=Envelope)
def edit(draft_id: str, line_id: str, request: LineEdit, t=Depends(tools)):
    return ok(t.update_po_line(draft_id, line_id, request))


@router.post("/drafts/{draft_id}/approve", response_model=Envelope)
def approve(draft_id: str, request: Review, t=Depends(tools)):
    return ok(Approval(t).execute(draft_id, request))


@router.post("/drafts/{draft_id}/reject", response_model=Envelope)
def reject(draft_id: str, request: Review, t=Depends(tools)):
    return ok(Approval(t).execute(draft_id, request, approve=False))


@router.get("/drafts/{draft_id}/export")
def export(draft_id: str, t=Depends(tools)):
    result = t.export_po(draft_id)
    return Response(result["content"], media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{result["filename"]}"'})


@router.get("/drafts/{draft_id}/history", response_model=Envelope)
def history(draft_id: str, t=Depends(tools)):
    return ok(t.approval_history(draft_id))


@router.get("/audit", response_model=Envelope)
def audit(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), t=Depends(tools)):
    return ok(t.list_resources("audit", limit, offset))


@router.post("/agent/review", response_model=Envelope)
def agent_review(request: RunRequest, t=Depends(tools)):
    return ok(ProcurementAgent(t).daily_review(request))


@router.post("/agent/runs/{run_id}/resume", response_model=Envelope)
def agent_resume(run_id: str, t=Depends(tools)):
    return ok(ProcurementAgent(t).resume(run_id))


@router.post("/agent/message", response_model=Envelope)
def agent_message(request: MessageRequest, t=Depends(tools)):
    return ok(t.agent_message(request))


@router.get("/demo/{scenario}", response_model=Envelope)
def demo_dataset(scenario: str, t=Depends(tools)):
    from datetime import date, timedelta
    from backend.demo import dataset, run_request
    if scenario not in {"normal", "incoming", "exceptions"}:
        raise BusinessError("Unknown synthetic scenario", "NOT_FOUND", 404)
    today = date.today()
    data = dataset(today, with_exceptions=scenario == "exceptions")
    if scenario == "incoming":
        data["open_po"] = [
            dict(sku_id="SKU-001", po_number="SYNTHETIC-TIMELY", quantity=100, arrival_date=(today+timedelta(days=2)).isoformat(), status="OPEN"),
            dict(sku_id="SKU-002", po_number="SYNTHETIC-LATE", quantity=100, arrival_date=(today+timedelta(days=8)).isoformat(), status="OPEN")]
    policy = run_request("", today).model_dump(mode="json", exclude={"batch_id"})
    return ok({"dataset": data, "policy": policy})
