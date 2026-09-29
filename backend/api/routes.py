from typing import Any
from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from backend.agent.procurement import ProcurementAgent
from backend.agent.messages import MessageRequest
from backend.api.dependencies import (
    authenticated_user, finance_tools, purchasing_tools, reviewer_tools, tools,
    workspace_identity, write_tools,
)
from backend.db.session import get_session
from backend.domain.intake import MAX_BYTES
from backend.domain.schemas import (
    LineEdit, MemberInvite, MemberUpdate, Resolution, Review, RunRequest,
    SimulationRequest, WorkspaceCreate, WorkspaceUpdate,
)
from backend.models.entities import Organization, Workspace, WorkspaceMembership
from backend.skills.workflows import Approval, ExceptionResolution
from backend.tools.runtime import BusinessError, serial


class Envelope(BaseModel):
    data: Any


router = APIRouter(prefix="/api/v1")


def ok(data):
    return {"data": data}


def workspace_payload(db, membership):
    workspace = db.get(Workspace, membership.workspace_id)
    organization = db.get(Organization, workspace.org_id)
    return {
        "id": workspace.id,
        "organization_id": organization.id,
        "organization_name": organization.name,
        "name": workspace.name,
        "business_entity": workspace.business_entity,
        "warehouse": workspace.warehouse,
        "currency": workspace.currency,
        "finance_threshold": str(workspace.finance_threshold),
        "role": membership.role,
    }


@router.get("/workspaces", response_model=Envelope)
def workspaces(db=Depends(get_session), user=Depends(authenticated_user)):
    if user["auth_type"] == "api_key":
        workspace = db.get(Workspace, user["workspace_id"])
        if workspace is None:
            return ok([])
        organization = db.get(Organization, workspace.org_id)
        return ok([{
            "id": workspace.id, "organization_id": organization.id,
            "organization_name": organization.name, "name": workspace.name,
            "business_entity": workspace.business_entity, "warehouse": workspace.warehouse,
            "currency": workspace.currency, "finance_threshold": str(workspace.finance_threshold),
            "role": user["role"],
        }])
    memberships = list(db.scalars(select(WorkspaceMembership).where(or_(
        WorkspaceMembership.user_id == user["user_id"],
        func.lower(WorkspaceMembership.email) == user["email"],
    )).order_by(WorkspaceMembership.created_at, WorkspaceMembership.id)))
    claimed = False
    for membership in memberships:
        if membership.user_id is None:
            membership.user_id = user["user_id"]
            claimed = True
    if claimed:
        db.commit()
    return ok([workspace_payload(db, membership) for membership in memberships])


@router.post("/workspaces", response_model=Envelope, status_code=201)
def create_workspace(request: WorkspaceCreate, db=Depends(get_session), user=Depends(authenticated_user)):
    if user["auth_type"] != "jwt":
        raise BusinessError("A signed-in user is required", "FORBIDDEN", 403)
    organization = Organization(name=request.organization_name)
    db.add(organization)
    db.flush()
    workspace = Workspace(
        org_id=organization.id, name=request.name, business_entity=request.business_entity,
        warehouse=request.warehouse, currency=request.currency,
        finance_threshold=request.finance_threshold,
    )
    db.add(workspace)
    db.flush()
    membership = WorkspaceMembership(
        workspace_id=workspace.id, user_id=user["user_id"], email=user["email"],
        display_name=user["actor"], role="owner",
    )
    db.add(membership)
    db.commit()
    return ok(workspace_payload(db, membership))


def _selected_workspace(db, workspace_id, identity):
    if identity["workspace_id"] != workspace_id:
        raise BusinessError("Workspace not found", "NOT_FOUND", 404)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise BusinessError("Workspace not found", "NOT_FOUND", 404)
    return workspace


def _owner(identity):
    if identity["role"] != "owner":
        raise BusinessError("Workspace owner permission required", "FORBIDDEN", 403)


@router.patch("/workspaces/{workspace_id}", response_model=Envelope)
def update_workspace(workspace_id: str, request: WorkspaceUpdate, db=Depends(get_session),
                     identity=Depends(workspace_identity)):
    _owner(identity)
    workspace = _selected_workspace(db, workspace_id, identity)
    for key, value in request.model_dump().items():
        setattr(workspace, key, value)
    db.commit()
    membership = db.scalar(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == workspace_id,
        WorkspaceMembership.user_id == identity["user_id"],
    ))
    return ok(workspace_payload(db, membership))


@router.get("/workspaces/{workspace_id}/members", response_model=Envelope)
def members(workspace_id: str, db=Depends(get_session), identity=Depends(workspace_identity)):
    _owner(identity)
    _selected_workspace(db, workspace_id, identity)
    return ok(serial(list(db.scalars(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == workspace_id
    ).order_by(WorkspaceMembership.created_at, WorkspaceMembership.id)))))


@router.post("/workspaces/{workspace_id}/members", response_model=Envelope, status_code=201)
def invite_member(workspace_id: str, request: MemberInvite, db=Depends(get_session),
                  identity=Depends(workspace_identity)):
    _owner(identity)
    _selected_workspace(db, workspace_id, identity)
    email = request.email.lower()
    existing = db.scalar(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == workspace_id,
        func.lower(WorkspaceMembership.email) == email,
    ))
    if existing:
        existing.display_name, existing.role = request.display_name, request.role
        member = existing
    else:
        member = WorkspaceMembership(
            workspace_id=workspace_id, user_id=None, email=email,
            display_name=request.display_name, role=request.role,
        )
        db.add(member)
    db.commit()
    return ok(serial(member))


@router.patch("/workspaces/{workspace_id}/members/{member_id}", response_model=Envelope)
def update_member(workspace_id: str, member_id: str, request: MemberUpdate,
                  db=Depends(get_session), identity=Depends(workspace_identity)):
    _owner(identity)
    _selected_workspace(db, workspace_id, identity)
    member = db.get(WorkspaceMembership, member_id)
    if member is None or member.workspace_id != workspace_id or member.role == "owner":
        raise BusinessError("Member not found or cannot be changed", "NOT_FOUND", 404)
    member.role = request.role
    db.commit()
    return ok(serial(member))


@router.delete("/workspaces/{workspace_id}/members/{member_id}", response_model=Envelope)
def remove_member(workspace_id: str, member_id: str, db=Depends(get_session),
                  identity=Depends(workspace_identity)):
    _owner(identity)
    _selected_workspace(db, workspace_id, identity)
    member = db.get(WorkspaceMembership, member_id)
    if member is None or member.workspace_id != workspace_id or member.role == "owner":
        raise BusinessError("Member not found or cannot be removed", "NOT_FOUND", 404)
    db.delete(member)
    db.commit()
    return ok({"id": member_id, "removed": True})


@router.post("/imports", response_model=Envelope, status_code=201)
def import_json(dataset: dict, filename: str = Query("dataset.json", min_length=1, max_length=255), t=Depends(write_tools)):
    return ok(t.import_dataset(dataset, filename))


@router.post("/imports/upload", response_model=Envelope, status_code=201)
async def upload(files: list[UploadFile] = File(...), t=Depends(write_tools)):
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


@router.delete("/imports/{batch_id}", response_model=Envelope)
def delete_import(batch_id: str, t=Depends(write_tools)):
    return ok(t.delete_import(batch_id))


@router.post("/runs", response_model=Envelope, status_code=201)
def create_run(request: RunRequest, t=Depends(write_tools)):
    return ok(t.create_procurement_run(request))


@router.get("/runs", response_model=Envelope)
def runs(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), t=Depends(tools)):
    return ok(t.list_resources("runs", limit, offset))


@router.post("/runs/{run_id}/check", response_model=Envelope)
def check(run_id: str, t=Depends(write_tools)):
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
def rerun(run_id: str, sku_id: str, t=Depends(write_tools)):
    return ok(t.rerun_sku(run_id, sku_id))


@router.patch("/runs/{run_id}/skus/{sku_id}/context", response_model=Envelope)
def correct_context(run_id: str, sku_id: str, request: Resolution, t=Depends(write_tools)):
    return ok(t.update_sku_context(run_id, sku_id, request))


@router.get("/runs/{run_id}/exceptions", response_model=Envelope)
def exceptions(run_id: str, t=Depends(tools)):
    return ok(t.list_exceptions(run_id))


@router.post("/exceptions/{exception_id}/resolve", response_model=Envelope)
def resolve(exception_id: str, request: Resolution, t=Depends(write_tools)):
    return ok(ExceptionResolution(t).execute(exception_id, request))


@router.post("/runs/{run_id}/drafts", response_model=Envelope)
def generate(run_id: str, t=Depends(write_tools)):
    return ok(t.generate_po_drafts(run_id))


@router.get("/drafts/{draft_id}", response_model=Envelope)
def draft(draft_id: str, t=Depends(tools)):
    return ok(t.get_po_draft(draft_id))


@router.get("/runs/{run_id}/drafts", response_model=Envelope)
def list_drafts(run_id: str, t=Depends(tools)):
    return ok(t.list_po_drafts(run_id))


@router.get("/runs/{run_id}/cockpit", response_model=Envelope)
def cockpit(run_id: str, t=Depends(tools)):
    return ok(t.procurement_cockpit(run_id))


@router.post("/runs/{run_id}/simulate", response_model=Envelope)
def simulate(run_id: str, request: SimulationRequest, t=Depends(tools)):
    return ok(t.simulate_procurement(run_id, request))


@router.patch("/drafts/{draft_id}/lines/{line_id}", response_model=Envelope)
def edit(draft_id: str, line_id: str, request: LineEdit, t=Depends(write_tools)):
    return ok(t.update_po_line(draft_id, line_id, request))


@router.post("/drafts/{draft_id}/approve", response_model=Envelope)
def approve(draft_id: str, request: Review, t=Depends(purchasing_tools)):
    return ok(Approval(t).execute(draft_id, request))


@router.post("/drafts/{draft_id}/reject", response_model=Envelope)
def reject(draft_id: str, request: Review, t=Depends(reviewer_tools)):
    return ok(Approval(t).execute(draft_id, request, approve=False))


@router.post("/drafts/{draft_id}/finance-approve", response_model=Envelope)
def finance_approve(draft_id: str, request: Review, t=Depends(finance_tools)):
    return ok(t.finance_approve_po(draft_id, request))


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
def agent_review(request: RunRequest, t=Depends(write_tools)):
    return ok(ProcurementAgent(t).daily_review(request))


@router.post("/agent/runs/{run_id}/resume", response_model=Envelope)
def agent_resume(run_id: str, t=Depends(write_tools)):
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
