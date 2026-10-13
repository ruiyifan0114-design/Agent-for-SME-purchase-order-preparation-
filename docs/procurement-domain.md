# Extended procurement domain

The original target-stock engine remains the default. Advanced behavior is implemented in pure modules under `backend/domain/inventory`, `sourcing`, `pricing`, `receiving`, `matching` and `approval`. These functions accept explicit inputs and return a calculation trace containing inputs, applied rule, intermediate values, result, data source and rule version. DeepSeek has no role in these calculations.

## Deterministic capabilities

- Supplier ranking compares landed cost, lead time, MOQ, pack size, capacity and a weighted performance score. Pairwise split allocations are evaluated with a bounded 10,000-candidate limit.
- Pricing selects an effective contract price first, otherwise the greatest eligible tier, otherwise base price. Freight, additional cost, duty, tax and an explicit exchange-rate snapshot produce landed cost.
- Inventory policy supports the legacy target-stock rule and an optional service-level safety stock, reorder point and EOQ rule. ABC/XYZ, holding cost, stockout cost and seasonal metadata are retained in the trace.
- PO lifecycle separates approval status from DRAFT/SENT/PARTIALLY_RECEIVED/RECEIVED/DELAYED/CANCELLED/RETURNED operational status.
- Receipts maintain received, returned and open quantities and reject over-receipt.
- Invoice matching compares PO, posted goods receipts and invoice references, quantity and price using explicit tolerances.
- Approval matrices filter by amount, cost center, supplier and risk, preserve ordered steps, and record delegation IDs in approval events.

## APIs

- `POST /api/v1/domain/sourcing/recommend`
- `POST /api/v1/runs/{run_id}/skus/{sku_id}/sourcing` saves an explainable allocation; the normal draft generator then creates one supplier draft per allocation.
- `POST /api/v1/domain/inventory/evaluate`
- `GET|POST /api/v1/domain/{supplier-performance|commercial-agreements|inventory-policies|approval-rules|delegations|budgets}`
- `PATCH /api/v1/drafts/{id}/finance`
- `POST /api/v1/drafts/{id}/lifecycle`
- `POST /api/v1/drafts/{id}/receipts`
- `POST /api/v1/drafts/{id}/invoices`
- `GET /api/v1/drafts/{id}/approval-plan`
- `POST /api/v1/drafts/{id}/matrix-approve`

Existing import, run, draft and approval endpoints remain compatible. Matrix rules effective at run creation are snapshotted in `rules_snapshot.approval_matrix`; later rule edits do not change that run. Draft modifications invalidate prior matrix approvals. Delegation eligibility is evaluated at the time of approval and recorded in its audit event.

The PO page includes human-entered lifecycle, receipt/return and single-line invoice forms. Receipt-derived statuses cannot be set manually. Returned stock reduces net receipts; replacement receipts may replenish the returned quantity. Invoice matching uses cumulative quantities across recorded invoices, including unresolved invoices, and net posted receipts. Unresolved invoices must be reconciled before further invoicing; credit notes and invoice correction workflows are not implemented.

Foreign sourcing offers require `fx_rate`, `fx_date` and `fx_source`. A supplier PO may not mix transaction currencies or FX rates. Supplier-selection charges are copied into the PO; additional procurement charges are included in the freight/additional-cost bucket. Marking a PO sent only records a human action. Cancellation after receipt or invoicing is blocked pending financial reconciliation.

## Synthetic scenarios

`GET /api/v1/demo/advanced/{scenario}` supports `supplier-comparison`, `split-order`, `delayed-supplier`, `tier-pricing`, `safety-stock-reorder-point`, `partial-receipt`, `three-way-match-exception`, and `approval-escalation`.

The system does not contact suppliers, transmit purchase orders, or autonomously commit purchases.
