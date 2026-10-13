from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Whole = Annotated[int, Field(strict=True, ge=0, le=100_000_000)]
Positive = Annotated[int, Field(strict=True, gt=0, le=100_000_000)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Price = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=4, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DemoCredentials(StrictModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    password: str = Field(min_length=8, max_length=128)


class WorkspaceCreate(StrictModel):
    organization_name: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=2, max_length=200)
    business_entity: str = Field(min_length=2, max_length=200)
    warehouse: str = Field(min_length=1, max_length=100)
    currency: str = Field(default="SGD", pattern=r"^[A-Z]{3}$")
    finance_threshold: Decimal = Field(default=Decimal("5000"), ge=0, max_digits=18, decimal_places=2)


class WorkspaceUpdate(StrictModel):
    name: str = Field(min_length=2, max_length=200)
    business_entity: str = Field(min_length=2, max_length=200)
    warehouse: str = Field(min_length=1, max_length=100)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    finance_threshold: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


class RuleSetCreate(StrictModel):
    effective_from: datetime
    effective_to: datetime | None = None
    default_horizon_days: int = Field(default=30, ge=1, le=365)
    inventory_max_age_days: int = Field(default=7, ge=0, le=3650)
    commercial_max_age_days: int = Field(default=90, ge=0, le=3650)
    finance_threshold: Decimal = Field(default=Decimal("5000"), ge=0, max_digits=18, decimal_places=2)
    currency: Currency = "SGD"
    matching_quantity_tolerance: Whole = 0
    matching_price_tolerance_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)

    @model_validator(mode="after")
    def valid_window(self):
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be later than effective_from")
        return self


class JobCreate(StrictModel):
    job_type: Literal["import_dataset", "procurement_check", "generate_po_drafts"]
    resource_id: str | None = Field(default=None, min_length=1, max_length=36)
    dataset: dict | None = None
    filename: str = Field(default="dataset.json", min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def valid_payload(self):
        if self.job_type == "import_dataset" and self.dataset is None:
            raise ValueError("dataset is required for import_dataset jobs")
        if self.job_type != "import_dataset" and self.resource_id is None:
            raise ValueError("resource_id is required for this job type")
        return self


class MemberInvite(StrictModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str = Field(min_length=2, max_length=200)
    role: str = Field(pattern=r"^(procurement|purchasing|finance|viewer)$")


class MemberUpdate(StrictModel):
    role: str = Field(pattern=r"^(procurement|purchasing|finance|viewer)$")


class SKURow(StrictModel):
    sku_id: Code
    description: Annotated[str, Field(min_length=1, max_length=500)]
    uom: Annotated[str, Field(min_length=1, max_length=30)]
    active: bool = True
    safety_stock: Whole | None = None
    target_stock: Whole | None = None


class SupplierRow(StrictModel):
    supplier_id: Code
    supplier_name: Annotated[str, Field(min_length=1, max_length=500)]
    approved: bool | None = None
    currency: Currency | None = None


class CommercialRow(StrictModel):
    sku_id: Code
    supplier_id: Code | None = None
    approved_for_sku: bool | None = None
    unit_price: Price | None = None
    currency: Currency | None = None
    moq: Whole | None = None
    pack_multiple: Positive | None = None
    lead_time_days: Annotated[int, Field(strict=True, ge=0, le=3650)] | None = None
    updated_at: date | None = None


class InventoryRow(StrictModel):
    sku_id: Code
    on_hand: Whole | None = None
    snapshot_date: date | None = None


class DemandRow(StrictModel):
    sku_id: Code
    quantity: Whole | None = None
    need_date: date | None = None


class OpenPORow(StrictModel):
    sku_id: Code
    po_number: Code
    quantity: Whole | None = None
    arrival_date: date | None = None
    status: Literal["OPEN", "CLOSED", "CANCELLED"] = "OPEN"


class Dataset(StrictModel):
    sku_master: list[SKURow]
    supplier_master: list[SupplierRow]
    supplier_sku: list[CommercialRow]
    inventory_snapshot: list[InventoryRow]
    demand: list[DemandRow]
    open_po: list[OpenPORow]


class RunRequest(StrictModel):
    batch_id: str
    as_of: date
    horizon: Annotated[int, Field(strict=True, ge=1, le=365)]
    currency: Currency
    warehouse: Annotated[str, Field(min_length=1, max_length=100)]
    inventory_max_age_days: Annotated[int, Field(strict=True, ge=0, le=3650)]
    commercial_max_age_days: Annotated[int, Field(strict=True, ge=0, le=3650)]


class Context(StrictModel):
    sku: SKURow
    suppliers: list[SupplierRow]
    commercial: list[CommercialRow]
    inventory: list[InventoryRow]
    demand: list[DemandRow]
    open_po: list[OpenPORow]

    @model_validator(mode="after")
    def same_sku(self):
        for key in ("commercial", "inventory", "demand", "open_po"):
            if any(r.sku_id != self.sku.sku_id for r in getattr(self, key)):
                raise ValueError("Correction rows must belong to the affected SKU")
        ids = [r.supplier_id for r in self.suppliers]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate supplier IDs")
        return self


class Resolution(StrictModel):
    expected_revision: Positive
    reason: Annotated[str, Field(min_length=3, max_length=2000)]
    # Full replacement context makes the proposed correction explicit and auditable.
    context: Context


class LineEdit(StrictModel):
    expected_version: Positive
    reason: Annotated[str, Field(min_length=3, max_length=2000)]
    quantity: Positive | None = None
    unit_price: Price | None = None

    @model_validator(mode="after")
    def has_edit(self):
        if self.quantity is None and self.unit_price is None:
            raise ValueError("Provide quantity or unit_price")
        return self


class Review(StrictModel):
    expected_version: Positive
    comment: Annotated[str, Field(min_length=1, max_length=2000)]
    confirm: Literal[True]


class SimulationRequest(StrictModel):
    """Bounded, read-only policy changes for deterministic scenario comparison."""
    horizon: Annotated[int, Field(strict=True, ge=1, le=365)] | None = None
    demand_percent: Annotated[int, Field(strict=True, ge=50, le=200)] = 100
    safety_stock_percent: Annotated[int, Field(strict=True, ge=50, le=200)] = 100
    lead_time_delta_days: Annotated[int, Field(strict=True, ge=-30, le=90)] = 0


class SourcingRequest(StrictModel):
    required_quantity: Positive
    as_of: date
    offers: list[dict] = Field(min_length=1, max_length=20)
    weights: dict = Field(default_factory=dict)
    allow_split: bool = True


class InventoryPolicyRequest(StrictModel):
    inputs: dict
    policy: dict


class ReceiptLineRequest(StrictModel):
    po_line_id: str
    quantity: Whole
    rejected_quantity: Whole = 0
    returned_quantity: Whole = 0


class ReceiptRequest(StrictModel):
    external_id: str = Field(min_length=1, max_length=100)
    received_at: datetime
    lines: list[ReceiptLineRequest] = Field(min_length=1, max_length=1000)


class InvoiceLineRequest(StrictModel):
    po_line_id: str
    sku_id: Code
    quantity: Positive
    unit_price: Price


class InvoiceRequest(StrictModel):
    supplier_id: Code
    invoice_number: str = Field(min_length=1, max_length=100)
    invoice_date: date
    currency: Currency
    exchange_rate: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    exchange_rate_date: date
    exchange_rate_source: str = Field(min_length=1, max_length=100)
    lines: list[InvoiceLineRequest] = Field(min_length=1, max_length=1000)
    quantity_tolerance: Whole = 0
    price_tolerance_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class LifecycleRequest(StrictModel):
    target_status: Literal["SENT", "PARTIALLY_RECEIVED", "RECEIVED", "DELAYED", "CANCELLED", "RETURNED"]
    reason: str = Field(min_length=1, max_length=2000)


class AgentProposalCreate(StrictModel):
    proposal_type: Literal["PO_LINE_EDIT", "PO_APPROVAL"]
    target_id: str = Field(min_length=1, max_length=36)
    expected_version: Positive
    exact_change: dict
    reason: str = Field(min_length=3, max_length=2000)
    interaction_id: str | None = Field(default=None, max_length=36)


class AgentProposalConfirm(StrictModel):
    confirm: Literal[True]


class AgentConversationCreate(StrictModel):
    title: str = Field(default="New procurement chat", min_length=1, max_length=120)
    run_id: str | None = Field(default=None, max_length=36)


class AgentConversationUpdate(StrictModel):
    title: str = Field(min_length=1, max_length=120)


class FinanceDimensionsRequest(StrictModel):
    cost_center: str | None = Field(default=None, max_length=80)
    project_code: str | None = Field(default=None, max_length=80)
    budget_code: str | None = Field(default=None, max_length=80)
    tax: Decimal = Field(default=Decimal("0"), ge=0)
    freight: Decimal = Field(default=Decimal("0"), ge=0)
    duty: Decimal = Field(default=Decimal("0"), ge=0)
    base_currency: Currency
    exchange_rate: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    exchange_rate_date: date
    exchange_rate_source: str = Field(min_length=1, max_length=100)


class SupplierPerformanceCreate(StrictModel):
    supplier_id: Code
    period_end: date
    on_time_rate: Decimal | None = Field(default=None, ge=0, le=1)
    lead_time_variance_days: Decimal | None = Field(default=None, ge=0)
    rejection_rate: Decimal | None = Field(default=None, ge=0, le=1)
    historical_score: Decimal | None = Field(default=None, ge=0, le=1)
    source_metadata: dict = Field(default_factory=dict)


class CommercialAgreementCreate(StrictModel):
    supplier_id: Code
    sku_id: Code
    agreement_number: str = Field(min_length=1, max_length=100)
    valid_from: date
    valid_to: date | None = None
    currency: Currency
    terms: dict
    rule_version: Positive = 1


class InventoryPolicyCreate(StrictModel):
    sku_id: Code
    policy_type: Literal["TARGET_STOCK", "ROP_EOQ"]
    parameters: dict
    rule_version: Positive
    effective_from: datetime
    effective_to: datetime | None = None


class ApprovalRuleCreate(StrictModel):
    rule_version: Positive
    sequence: Whole
    conditions: dict
    required_role: str = Field(min_length=1, max_length=50)
    effective_from: datetime
    effective_to: datetime | None = None


class DelegationCreate(StrictModel):
    delegator_user_id: str = Field(min_length=1, max_length=100)
    delegator_role: str = Field(min_length=1, max_length=50)
    delegate_user_id: str = Field(min_length=1, max_length=100)
    delegate_role: str = Field(min_length=1, max_length=50)
    valid_from: datetime
    valid_to: datetime
    reason: str = Field(min_length=3, max_length=2000)


class BudgetCreate(StrictModel):
    budget_code: str = Field(min_length=1, max_length=80)
    cost_center: str | None = Field(default=None, max_length=80)
    project_code: str | None = Field(default=None, max_length=80)
    currency: Currency
    authorized_amount: Decimal = Field(gt=0)
