from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from backend.db.session import Base

LEGACY_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
LEGACY_WORKSPACE_ID = "00000000-0000-0000-0000-000000000002"


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)


class Organization(Identity, Base):
    __tablename__ = "organization"
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Workspace(Identity, Base):
    __tablename__ = "workspace"
    org_id: Mapped[str] = mapped_column(ForeignKey("organization.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    business_entity: Mapped[str] = mapped_column(String(200))
    warehouse: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3), default="SGD")
    finance_threshold: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("5000"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RuleSet(Identity, Base):
    """Immutable, effective-dated workspace policy revision."""
    __tablename__ = "rule_set"
    __table_args__ = (
        UniqueConstraint("workspace_id", "rule_version"),
        CheckConstraint("rule_version > 0"),
    )
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    rule_version: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    rules: Mapped[dict] = mapped_column(JSON)
    approval_policy: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkspaceMembership(Identity, Base):
    __tablename__ = "workspace_membership"
    __table_args__ = (
        UniqueConstraint("workspace_id", "email"),
        UniqueConstraint("workspace_id", "user_id"),
        CheckConstraint("role IN ('owner','procurement','purchasing','finance','viewer')"),
    )
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(100), index=True)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DemoAccount(Identity, Base):
    __tablename__ = "demo_account"
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DemoSession(Identity, Base):
    __tablename__ = "demo_session"
    account_id: Mapped[str] = mapped_column(ForeignKey("demo_account.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ImportBatch(Identity, Base):
    __tablename__ = "import_batch"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key"),
        UniqueConstraint("workspace_id", "source_system", "external_id"),
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspace.id"), index=True, default=LEGACY_WORKSPACE_ID
    )
    filename: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    source_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    source_system: Mapped[str] = mapped_column(String(80), default="manual")
    external_id: Mapped[str | None] = mapped_column(String(200))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_data: Mapped[dict] = mapped_column(JSON)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Source:
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batch.id"), index=True)
    source_system: Mapped[str] = mapped_column(String(80), default="manual")
    external_id: Mapped[str | None] = mapped_column(String(200), index=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class SKU(Identity, Source, Base):
    __tablename__ = "sku_master"
    __table_args__ = (UniqueConstraint("batch_id", "sku_id"),)
    sku_id: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    uom: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean)
    safety_stock: Mapped[int | None] = mapped_column(Integer)
    target_stock: Mapped[int | None] = mapped_column(Integer)


class Supplier(Identity, Source, Base):
    __tablename__ = "supplier_master"
    __table_args__ = (UniqueConstraint("batch_id", "supplier_id"),)
    supplier_id: Mapped[str] = mapped_column(String(80))
    supplier_name: Mapped[str] = mapped_column(Text)
    approved: Mapped[bool | None] = mapped_column(Boolean)
    currency: Mapped[str | None] = mapped_column(String(3))


class SupplierSKU(Identity, Source, Base):
    __tablename__ = "supplier_sku"
    __table_args__ = (ForeignKeyConstraint(["batch_id", "sku_id"], ["sku_master.batch_id", "sku_master.sku_id"]),)
    sku_id: Mapped[str] = mapped_column(String(80), index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(80))
    approved_for_sku: Mapped[bool | None] = mapped_column(Boolean)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str | None] = mapped_column(String(3))
    moq: Mapped[int | None] = mapped_column(Integer)
    pack_multiple: Mapped[int | None] = mapped_column(Integer)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[date | None] = mapped_column(Date)


class SupplierPerformance(Identity, Base):
    __tablename__ = "supplier_performance"
    __table_args__ = (UniqueConstraint("workspace_id", "supplier_id", "period_end"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(String(80), index=True)
    period_end: Mapped[date] = mapped_column(Date)
    on_time_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    lead_time_variance_days: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    rejection_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    historical_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class CommercialAgreement(Identity, Base):
    __tablename__ = "commercial_agreement"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(String(80), index=True)
    sku_id: Mapped[str] = mapped_column(String(80), index=True)
    agreement_number: Mapped[str] = mapped_column(String(100))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    terms: Mapped[dict] = mapped_column(JSON)
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SKUInventoryPolicy(Identity, Base):
    __tablename__ = "sku_inventory_policy"
    __table_args__ = (UniqueConstraint("workspace_id", "sku_id", "rule_version"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    sku_id: Mapped[str] = mapped_column(String(80), index=True)
    policy_type: Mapped[str] = mapped_column(String(30))
    parameters: Mapped[dict] = mapped_column(JSON)
    rule_version: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Inventory(Identity, Source, Base):
    __tablename__ = "inventory_snapshot"
    __table_args__ = (ForeignKeyConstraint(["batch_id", "sku_id"], ["sku_master.batch_id", "sku_master.sku_id"]),)
    sku_id: Mapped[str] = mapped_column(String(80), index=True)
    on_hand: Mapped[int | None] = mapped_column(Integer)
    snapshot_date: Mapped[date | None] = mapped_column(Date)


class Demand(Identity, Source, Base):
    __tablename__ = "demand"
    __table_args__ = (ForeignKeyConstraint(["batch_id", "sku_id"], ["sku_master.batch_id", "sku_master.sku_id"]),)
    sku_id: Mapped[str] = mapped_column(String(80), index=True)
    quantity: Mapped[int | None] = mapped_column(Integer)
    need_date: Mapped[date | None] = mapped_column(Date)


class OpenPO(Identity, Source, Base):
    __tablename__ = "open_po"
    __table_args__ = (ForeignKeyConstraint(["batch_id", "sku_id"], ["sku_master.batch_id", "sku_master.sku_id"]),)
    sku_id: Mapped[str] = mapped_column(String(80), index=True)
    po_number: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int | None] = mapped_column(Integer)
    arrival_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30))


class ProcurementRun(Identity, Base):
    __tablename__ = "procurement_run"
    __table_args__ = (UniqueConstraint("batch_id", "idempotency_key"),)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batch.id"))
    status: Mapped[str] = mapped_column(String(30), default="CREATED")
    as_of: Mapped[date] = mapped_column(Date)
    horizon: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    warehouse: Mapped[str] = mapped_column(String(100))
    inventory_max_age_days: Mapped[int] = mapped_column(Integer)
    commercial_max_age_days: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    rule_set_id: Mapped[str] = mapped_column(ForeignKey("rule_set.id"), index=True)
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    rules_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    approval_policy_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_sku_count: Mapped[int] = mapped_column(Integer)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    reorder_count: Mapped[int] = mapped_column(Integer, default=0)
    no_reorder_count: Mapped[int] = mapped_column(Integer, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SKUCheckResult(Identity, Base):
    __tablename__ = "sku_check_result"
    __table_args__ = (UniqueConstraint("run_id", "sku_id"), CheckConstraint("status IN ('NO_REORDER','REORDER','BLOCKED')"))
    run_id: Mapped[str] = mapped_column(ForeignKey("procurement_run.id"), index=True)
    sku_id: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="BLOCKED")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    context: Mapped[dict] = mapped_column(JSON)
    on_hand: Mapped[int | None] = mapped_column(BigInteger)
    valid_incoming: Mapped[int | None] = mapped_column(BigInteger)
    demand_qty: Mapped[int | None] = mapped_column(BigInteger)
    projected_stock: Mapped[int | None] = mapped_column(BigInteger)
    raw_order_qty: Mapped[int | None] = mapped_column(BigInteger)
    final_order_qty: Mapped[int | None] = mapped_column(BigInteger)
    decision_reason: Mapped[str] = mapped_column(Text, default="Pending evaluation")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class SourcingDecision(Identity, Base):
    __tablename__ = "sourcing_decision"
    __table_args__ = (UniqueConstraint("result_id"),)
    result_id: Mapped[str] = mapped_column(ForeignKey("sku_check_result.id"), index=True)
    rule_version: Mapped[int] = mapped_column(Integer)
    trace: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExceptionRecord(Identity, Base):
    __tablename__ = "exception"
    run_id: Mapped[str] = mapped_column(ForeignKey("procurement_run.id"), index=True)
    result_id: Mapped[str] = mapped_column(ForeignKey("sku_check_result.id"), index=True)
    code: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    required_field: Mapped[str] = mapped_column(String(100))
    required_action: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="OPEN")
    resolved_value: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PODraft(Identity, Base):
    __tablename__ = "po_draft"
    __table_args__ = (UniqueConstraint("run_id", "supplier_id"),)
    run_id: Mapped[str] = mapped_column(ForeignKey("procurement_run.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(String(80))
    supplier_name: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3))
    warehouse: Mapped[str] = mapped_column(String(100))
    order_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, default=1)
    total: Mapped[Decimal] = mapped_column(Numeric(32, 2), default=0)
    reviewer: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finance_reviewer: Mapped[str | None] = mapped_column(String(200))
    finance_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lifecycle_status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    cost_center: Mapped[str | None] = mapped_column(String(80))
    project_code: Mapped[str | None] = mapped_column(String(80))
    budget_code: Mapped[str | None] = mapped_column(String(80))
    tax: Mapped[Decimal] = mapped_column(Numeric(32, 2), default=0)
    freight: Mapped[Decimal] = mapped_column(Numeric(32, 2), default=0)
    duty: Mapped[Decimal] = mapped_column(Numeric(32, 2), default=0)
    landed_cost: Mapped[Decimal] = mapped_column(Numeric(32, 2), default=0)
    base_currency: Mapped[str | None] = mapped_column(String(3))
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    exchange_rate_date: Mapped[date | None] = mapped_column(Date)
    exchange_rate_source: Mapped[str | None] = mapped_column(String(100))


class POLine(Identity, Base):
    __tablename__ = "po_line"
    __table_args__ = (UniqueConstraint("result_id", "draft_id"), CheckConstraint("quantity > 0"),
                      CheckConstraint("unit_price > 0"))
    draft_id: Mapped[str] = mapped_column(ForeignKey("po_draft.id"), index=True)
    result_id: Mapped[str] = mapped_column(ForeignKey("sku_check_result.id"))
    result_revision: Mapped[int] = mapped_column(Integer)
    sku_id: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    uom: Mapped[str] = mapped_column(String(30))
    quantity: Mapped[int] = mapped_column(BigInteger)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(32, 2))
    need_date: Mapped[date] = mapped_column(Date)
    expected_delivery_date: Mapped[date] = mapped_column(Date)
    received_quantity: Mapped[int] = mapped_column(BigInteger, default=0)
    returned_quantity: Mapped[int] = mapped_column(BigInteger, default=0)
    open_quantity: Mapped[int] = mapped_column(BigInteger, default=0)


class ApprovalEvent(Identity, Base):
    __tablename__ = "approval_event"
    draft_id: Mapped[str] = mapped_column(ForeignKey("po_draft.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ToolExecutionLog(Identity, Base):
    __tablename__ = "tool_execution_log"
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspace.id"), index=True, default=LEGACY_WORKSPACE_ID
    )
    tool_name: Mapped[str] = mapped_column(String(100), index=True)
    actor: Mapped[str] = mapped_column(String(200))
    user_id: Mapped[str] = mapped_column(String(100), default="")
    correlation_id: Mapped[str] = mapped_column(String(64), default="")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    input: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict | list | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class JobRecord(Identity, Base):
    __tablename__ = "job_record"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    job_type: Mapped[str] = mapped_column(String(80), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | list | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[str] = mapped_column(String(64), default="")
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Budget(Identity, Base):
    __tablename__ = "budget"
    __table_args__ = (UniqueConstraint("workspace_id", "budget_code", "currency"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    budget_code: Mapped[str] = mapped_column(String(80))
    cost_center: Mapped[str | None] = mapped_column(String(80), index=True)
    project_code: Mapped[str | None] = mapped_column(String(80), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    authorized_amount: Mapped[Decimal] = mapped_column(Numeric(32, 2))
    committed_amount: Mapped[Decimal] = mapped_column(Numeric(32, 2), default=0)


class GoodsReceipt(Identity, Base):
    __tablename__ = "goods_receipt"
    __table_args__ = (UniqueConstraint("workspace_id", "external_id"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("po_draft.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(100))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="POSTED")
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(200))


class GoodsReceiptLine(Identity, Base):
    __tablename__ = "goods_receipt_line"
    receipt_id: Mapped[str] = mapped_column(ForeignKey("goods_receipt.id"), index=True)
    po_line_id: Mapped[str] = mapped_column(ForeignKey("po_line.id"), index=True)
    sku_id: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[int] = mapped_column(BigInteger)
    rejected_quantity: Mapped[int] = mapped_column(BigInteger, default=0)
    returned_quantity: Mapped[int] = mapped_column(BigInteger, default=0)


class SupplierInvoice(Identity, Base):
    __tablename__ = "supplier_invoice"
    __table_args__ = (UniqueConstraint("workspace_id", "supplier_id", "invoice_number"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("po_draft.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(String(80))
    invoice_number: Mapped[str] = mapped_column(String(100))
    invoice_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    exchange_rate_date: Mapped[date] = mapped_column(Date)
    exchange_rate_source: Mapped[str] = mapped_column(String(100))
    total: Mapped[Decimal] = mapped_column(Numeric(32, 2))
    status: Mapped[str] = mapped_column(String(30), default="PENDING_MATCH")


class SupplierInvoiceLine(Identity, Base):
    __tablename__ = "supplier_invoice_line"
    invoice_id: Mapped[str] = mapped_column(ForeignKey("supplier_invoice.id"), index=True)
    po_line_id: Mapped[str] = mapped_column(ForeignKey("po_line.id"), index=True)
    sku_id: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[int] = mapped_column(BigInteger)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    amount: Mapped[Decimal] = mapped_column(Numeric(32, 2))


class MatchResult(Identity, Base):
    __tablename__ = "match_result"
    invoice_id: Mapped[str] = mapped_column(ForeignKey("supplier_invoice.id"), index=True)
    po_line_id: Mapped[str] = mapped_column(ForeignKey("po_line.id"), index=True)
    status: Mapped[str] = mapped_column(String(30))
    rule_version: Mapped[int] = mapped_column(Integer)
    trace: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ApprovalMatrixRule(Identity, Base):
    __tablename__ = "approval_matrix_rule"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    rule_version: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    conditions: Mapped[dict] = mapped_column(JSON)
    required_role: Mapped[str] = mapped_column(String(50))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalDelegation(Identity, Base):
    __tablename__ = "approval_delegation"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    delegator_user_id: Mapped[str] = mapped_column(String(100), index=True)
    delegator_role: Mapped[str] = mapped_column(String(50))
    delegate_user_id: Mapped[str] = mapped_column(String(100), index=True)
    delegate_role: Mapped[str] = mapped_column(String(50))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
