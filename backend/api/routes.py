from typing import Any
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, Header, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select
from backend.auth.demo import (
    authenticate_demo_token, issue_session, password_hash, password_matches,
    remove_expired_sessions, token_digest,
)
from backend.agent.procurement import ProcurementAgent
from backend.agent.messages import MessageRequest
from backend.api.dependencies import (
    authenticated_user, finance_tools, purchasing_tools, reviewer_tools, tools,
    workspace_identity, write_tools,
)
from backend.db.session import get_session
from backend.domain.intake import MAX_BYTES
from backend.domain.schemas import (
    DemoCredentials, JobCreate, LineEdit, MemberInvite, MemberUpdate, Resolution, Review,
    ApprovalRuleCreate, BudgetCreate, CommercialAgreementCreate, DelegationCreate,
    FinanceDimensionsRequest, InventoryPolicyCreate, InventoryPolicyRequest, InvoiceRequest,
    LifecycleRequest, ReceiptRequest, RuleSetCreate, RunRequest, SimulationRequest,
    SourcingRequest, SupplierPerformanceCreate, WorkspaceCreate, WorkspaceUpdate,
)
from backend.jobs.service import JobService
from backend.models.entities import (
    DemoAccount, DemoSession, ImportBatch, JobRecord, Organization, RuleSet, ToolExecutionLog, Workspace,
    WorkspaceMembership,
)
from backend.skills.workflows import Approval, ExceptionResolution
from backend.tools.runtime import BusinessError, serial
from backend.domain.inventory.engine import inventory_policy
from backend.domain.sourcing.engine import rank_suppliers


class Envelope(BaseModel):
    data: Any


router = APIRouter(prefix="/api/v1")


def ok(data):
    return {"data": data}


@router.post("/auth/demo/register", response_model=Envelope, status_code=201)
def register_demo(request: DemoCredentials, db=Depends(get_session)):
    username = request.username.lower()
    if db.scalar(select(DemoAccount.id).where(DemoAccount.username == username)):
        raise BusinessError("That demo username is already in use", "USERNAME_TAKEN", 409)
    remove_expired_sessions(db)
    account = DemoAccount(
        username=username,
        display_name=request.username,
        password_hash=password_hash(request.password),
    )
    db.add(account)
    db.flush()
    return ok(issue_session(db, account))


@router.post("/auth/demo/login", response_model=Envelope)
def login_demo(request: DemoCredentials, db=Depends(get_session)):
    account = db.scalar(
        select(DemoAccount).where(DemoAccount.username == request.username.lower())
    )
    if account is None or not password_matches(request.password, account.password_hash):
        raise BusinessError("Incorrect demo username or password", "INVALID_CREDENTIALS", 401)
    remove_expired_sessions(db)
    return ok(issue_session(db, account))


@router.delete("/auth/demo/session", response_model=Envelope)
def logout_demo(authorization: str = Header(default=""), db=Depends(get_session)):
    token = authorization.removeprefix("Bearer ").strip()
    if not authenticate_demo_token(db, token):
        raise BusinessError("Valid demo authentication required", "UNAUTHORIZED", 401)
    db.execute(delete(DemoSession).where(DemoSession.token_hash == token_digest(token)))
    db.commit()
    return ok({"signed_out": True})


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
    if user["auth_type"] not in {"jwt", "demo"}:
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
    db.add(RuleSet(
        workspace_id=workspace.id, rule_version=1,
        effective_from=datetime.now(timezone.utc),
        rules={"replenishment_policy": "BELOW_SAFETY_TO_TARGET", "rounding_policy": "MOQ_PACK_CEILING"},
        approval_policy={"currency": workspace.currency, "finance_threshold": str(workspace.finance_threshold)},
        created_by=user["actor"],
    ))
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
    old_policy = (workspace.currency, workspace.finance_threshold)
    for key, value in request.model_dump().items():
        setattr(workspace, key, value)
    if old_policy != (workspace.currency, workspace.finance_threshold):
        latest = db.scalar(select(RuleSet).where(RuleSet.workspace_id == workspace_id)
                           .order_by(RuleSet.rule_version.desc()).limit(1))
        effective = datetime.now(timezone.utc)
        if latest and latest.effective_to is None:
            latest.effective_to = effective
        db.add(RuleSet(
            workspace_id=workspace_id, rule_version=(latest.rule_version if latest else 0) + 1,
            effective_from=effective,
            rules=(latest.rules if latest else {
                "replenishment_policy": "BELOW_SAFETY_TO_TARGET", "rounding_policy": "MOQ_PACK_CEILING"
            }),
            approval_policy={"currency": workspace.currency,
                             "finance_threshold": str(workspace.finance_threshold)},
            created_by=identity["actor"],
        ))
    db.commit()
    membership = db.scalar(select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == workspace_id,
        WorkspaceMembership.user_id == identity["user_id"],
    ))
    return ok(workspace_payload(db, membership))


@router.delete("/workspaces/{workspace_id}", response_model=Envelope)
def delete_workspace(workspace_id: str, db=Depends(get_session),
                     identity=Depends(workspace_identity)):
    _owner(identity)
    workspace = _selected_workspace(db, workspace_id, identity)
    if db.scalar(select(ImportBatch.id).where(ImportBatch.workspace_id == workspace_id).limit(1)):
        raise BusinessError(
            "This workspace contains procurement data and must be retained for audit history",
            "WORKSPACE_IN_USE",
            409,
        )
    organization_id = workspace.org_id
    db.execute(delete(ToolExecutionLog).where(ToolExecutionLog.workspace_id == workspace_id))
    db.execute(delete(JobRecord).where(JobRecord.workspace_id == workspace_id))
    db.execute(delete(RuleSet).where(RuleSet.workspace_id == workspace_id))
    db.execute(delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id))
    db.delete(workspace)
    db.flush()
    if not db.scalar(select(Workspace.id).where(Workspace.org_id == organization_id).limit(1)):
        organization = db.get(Organization, organization_id)
        if organization:
            db.delete(organization)
    db.commit()
    return ok({"id": workspace_id, "deleted": True})


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
def import_json(dataset: dict, filename: str = Query("dataset.json", min_length=1, max_length=255),
                idempotency_key: str = Header(default="", alias="Idempotency-Key"), t=Depends(write_tools)):
    return ok(t.import_dataset(dataset, filename, idempotency_key or None))


@router.post("/imports/upload", response_model=Envelope, status_code=201)
async def upload(files: list[UploadFile] = File(...),
                 idempotency_key: str = Header(default="", alias="Idempotency-Key"), t=Depends(write_tools)):
    if len(files) > 6:
        raise BusinessError("Provide at most 6 CSVs or one workbook", "INVALID_UPLOAD", 422)
    inputs, total = [], 0
    for file in files:
        content = await file.read(MAX_BYTES + 1)
        total += len(content)
        if total > MAX_BYTES:
            raise BusinessError("Upload exceeds 10 MiB", "PAYLOAD_TOO_LARGE", 413)
        inputs.append((file.filename or "unknown", content))
    return ok(t.import_files(inputs, idempotency_key or None))


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
def create_run(request: RunRequest, idempotency_key: str = Header(default="", alias="Idempotency-Key"),
               t=Depends(write_tools)):
    return ok(t.create_procurement_run(request, idempotency_key or None))


@router.get("/rules", response_model=Envelope)
def rules(t=Depends(tools)):
    return ok(t.list_rule_sets())


@router.post("/rules", response_model=Envelope, status_code=201)
def create_rules(request: RuleSetCreate, t=Depends(tools)):
    return ok(t.create_rule_set(request))


@router.post("/jobs", response_model=Envelope, status_code=202)
def create_job(request: JobCreate, t=Depends(write_tools)):
    return ok(serial(JobService(t.db, t).create(
        request.job_type, request.idempotency_key, resource_id=request.resource_id,
        dataset=request.dataset, filename=request.filename,
    )))


@router.get("/jobs/{job_id}", response_model=Envelope)
def get_job(job_id: str, t=Depends(tools)):
    return ok(serial(JobService(t.db, t).get(job_id)))


@router.post("/jobs/{job_id}/execute", response_model=Envelope)
def execute_job(job_id: str, t=Depends(write_tools)):
    return ok(serial(JobService(t.db, t).run(job_id)))


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


@router.post("/domain/inventory/evaluate", response_model=Envelope)
def evaluate_inventory_policy(request: InventoryPolicyRequest, t=Depends(tools)):
    try:
        return ok(inventory_policy(request.inputs, request.policy))
    except (ValueError, KeyError) as exc:
        raise BusinessError(str(exc), "INVALID_POLICY_INPUT", 422) from exc


@router.post("/domain/sourcing/recommend", response_model=Envelope)
def recommend_sourcing(request: SourcingRequest, t=Depends(tools)):
    try:
        return ok(rank_suppliers(request.required_quantity, request.offers, request.as_of,
                                 request.weights, request.allow_split))
    except (ValueError, KeyError) as exc:
        raise BusinessError(str(exc), "INVALID_SOURCING_INPUT", 422) from exc


@router.post("/runs/{run_id}/skus/{sku_id}/sourcing", response_model=Envelope)
def source_run_sku(run_id: str, sku_id: str, request: SourcingRequest, t=Depends(write_tools)):
    try:
        return ok(t.source_sku(run_id, sku_id, request))
    except (ValueError, KeyError) as exc:
        raise BusinessError(str(exc), "INVALID_SOURCING_INPUT", 422) from exc


@router.get("/domain/{kind}", response_model=Envelope)
def domain_records(kind: str, t=Depends(tools)):
    return ok(t.list_domain_records(kind))


@router.post("/domain/supplier-performance", response_model=Envelope, status_code=201)
def supplier_performance(request: SupplierPerformanceCreate, t=Depends(write_tools)):
    return ok(t.create_domain_record("supplier-performance", request))


@router.post("/domain/commercial-agreements", response_model=Envelope, status_code=201)
def commercial_agreement(request: CommercialAgreementCreate, t=Depends(write_tools)):
    return ok(t.create_domain_record("commercial-agreements", request))


@router.post("/domain/inventory-policies", response_model=Envelope, status_code=201)
def inventory_policy_record(request: InventoryPolicyCreate, t=Depends(write_tools)):
    return ok(t.create_domain_record("inventory-policies", request))


@router.post("/domain/approval-rules", response_model=Envelope, status_code=201)
def approval_rule(request: ApprovalRuleCreate, t=Depends(write_tools)):
    return ok(t.create_domain_record("approval-rules", request))


@router.post("/domain/delegations", response_model=Envelope, status_code=201)
def delegation(request: DelegationCreate, t=Depends(write_tools)):
    return ok(t.create_domain_record("delegations", request))


@router.post("/domain/budgets", response_model=Envelope, status_code=201)
def budget(request: BudgetCreate, t=Depends(write_tools)):
    return ok(t.create_domain_record("budgets", request))


@router.patch("/drafts/{draft_id}/lines/{line_id}", response_model=Envelope)
def edit(draft_id: str, line_id: str, request: LineEdit, t=Depends(write_tools)):
    return ok(t.update_po_line(draft_id, line_id, request))


@router.patch("/drafts/{draft_id}/finance", response_model=Envelope)
def finance_dimensions(draft_id: str, request: FinanceDimensionsRequest, t=Depends(write_tools)):
    return ok(t.set_finance_dimensions(draft_id, request))


@router.post("/drafts/{draft_id}/lifecycle", response_model=Envelope)
def lifecycle(draft_id: str, request: LifecycleRequest, t=Depends(write_tools)):
    return ok(t.transition_po_lifecycle(draft_id, request.target_status, request.reason))


@router.post("/drafts/{draft_id}/receipts", response_model=Envelope, status_code=201)
def receipt(draft_id: str, request: ReceiptRequest, t=Depends(write_tools)):
    return ok(t.record_goods_receipt(draft_id, request))


@router.post("/drafts/{draft_id}/invoices", response_model=Envelope, status_code=201)
def invoice(draft_id: str, request: InvoiceRequest, t=Depends(write_tools)):
    return ok(t.record_and_match_invoice(draft_id, request))


@router.post("/drafts/{draft_id}/approve", response_model=Envelope)
def approve(draft_id: str, request: Review, t=Depends(purchasing_tools)):
    return ok(Approval(t).execute(draft_id, request))


@router.get("/drafts/{draft_id}/approval-plan", response_model=Envelope)
def approval_plan(draft_id: str, t=Depends(tools)):
    return ok(t.approval_plan(draft_id))


@router.post("/drafts/{draft_id}/matrix-approve", response_model=Envelope)
def matrix_approve(draft_id: str, request: Review, t=Depends(reviewer_tools)):
    return ok(t.matrix_approve(draft_id, request))


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


@router.get("/demo/advanced/{scenario_name}", response_model=Envelope)
def advanced_demo(scenario_name: str, t=Depends(tools)):
    from backend.advanced_demo import scenario
    try:
        return ok(scenario(scenario_name))
    except KeyError as exc:
        raise BusinessError("Unknown advanced synthetic scenario", "NOT_FOUND", 404) from exc
