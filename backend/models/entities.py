from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from backend.db.session import Base


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)


class ImportBatch(Identity, Base):
    __tablename__ = "import_batch"
    filename: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    source_hash: Mapped[str] = mapped_column(String(64))
    raw_data: Mapped[dict] = mapped_column(JSON)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Source:
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batch.id"), index=True)


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
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batch.id"))
    status: Mapped[str] = mapped_column(String(30), default="CREATED")
    as_of: Mapped[date] = mapped_column(Date)
    horizon: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    warehouse: Mapped[str] = mapped_column(String(100))
    inventory_max_age_days: Mapped[int] = mapped_column(Integer)
    commercial_max_age_days: Mapped[int] = mapped_column(Integer)
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


class POLine(Identity, Base):
    __tablename__ = "po_line"
    __table_args__ = (UniqueConstraint("result_id"), CheckConstraint("quantity > 0"), CheckConstraint("unit_price > 0"))
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
    tool_name: Mapped[str] = mapped_column(String(100), index=True)
    actor: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))
    input: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict | list | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
