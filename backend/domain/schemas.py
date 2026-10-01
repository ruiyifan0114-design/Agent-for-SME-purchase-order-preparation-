from datetime import date
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
