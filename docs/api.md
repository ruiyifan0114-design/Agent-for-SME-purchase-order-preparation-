# Frontend API contract

Base: `/api/v1`. Hosted clients send `Authorization: Bearer <Supabase access token>`. Workspace-scoped routes also send an authorized `X-Workspace-ID`. Local-only legacy clients may use `X-API-Key` when `ALLOW_API_KEYS=true`. `/docs` provides the request schemas.
Dates use ISO strings, timestamps include timezone, money is serialized as decimal **strings**.
Success: `{"data": ...}`. Errors: `{"error":{"code":"...","message":"..."}}`.
Validation errors add `details` with field locations. CSV export returns a download response.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/workspaces` | List only the signed-in user's workspace memberships |
| POST | `/workspaces` | Create an organization/workspace and become its owner |
| PATCH | `/workspaces/{id}` | Owner updates business entity, warehouse, currency or approval threshold |
| GET | `/workspaces/{id}/members` | Owner lists workspace members |
| POST | `/workspaces/{id}/members` | Owner invites a member by email and assigns a role |
| PATCH | `/workspaces/{id}/members/{member_id}` | Owner changes a member's profile or role |
| DELETE | `/workspaces/{id}/members/{member_id}` | Owner removes a non-owner member |
| POST | `/imports` | Import JSON containing all six tables |
| POST | `/imports/upload` | Multipart `files`: six CSVs or one six-sheet XLSX |
| GET | `/imports` | Batches, `limit` (1–500), `offset` |
| GET | `/imports/{id}` | Stored validation status/issues |
| DELETE | `/imports/{id}` | Delete an unused import; batches referenced by a review remain immutable audit evidence |
| POST | `/runs` | Create run and freeze every active SKU context |
| GET | `/runs` | Runs, pagination |
| POST | `/runs/{id}/check` | Evaluate all not-yet-processed SKUs |
| GET | `/runs/{id}` | Stored summary and counts |
| GET | `/runs/{id}/results` | Every SKU result, reason, evidence and context |
| GET | `/runs/{id}/skus/{sku}` | One result and editable source context |
| POST | `/runs/{id}/skus/{sku}/rerun` | Rerun and invalidate dependent draft approval |
| PATCH | `/runs/{id}/skus/{sku}/context` | Human correction of source context; automatic rerun |
| GET | `/runs/{id}/exceptions` | Open and historical exceptions |
| POST | `/exceptions/{id}/resolve` | Human correction; selected exception must actually disappear |
| POST | `/runs/{id}/drafts` | Generate/reconcile supplier-grouped drafts, idempotently |
| GET | `/runs/{id}/cockpit` | Stored management metrics and material changes versus the previous run |
| POST | `/runs/{id}/simulate` | Read-only deterministic horizon/demand/stock-policy/lead-time scenario |
| GET | `/drafts/{id}` | Header, current version, lines, source references |
| PATCH | `/drafts/{id}/lines/{line_id}` | Human quantity/price edit; invalidate approval |
| POST | `/drafts/{id}/approve` | Explicit human approval |
| POST | `/drafts/{id}/finance-approve` | Finance role after Purchasing approval when the workspace threshold applies |
| POST | `/drafts/{id}/reject` | Human rejection |
| GET | `/drafts/{id}/export` | Approved-only pre-tax synthetic CSV |
| GET | `/drafts/{id}/history` | Approval/rejection/invalidation/export snapshots |
| GET | `/audit` | Tool logs, pagination |
| POST | `/agent/review` | Create run, check all, generate drafts, return stored report |
| POST | `/agent/runs/{id}/resume` | Resume unfinished scan/reconcile drafts/read latest report |

## Exceptions and corrections

Fetch a SKU result; copy its complete `context`, correct only the intended values, then send:

```json
{
  "expected_revision": 1,
  "reason": "Human confirmed the synthetic supplier price",
  "context": {
    "sku": {"sku_id":"SKU-001","description":"Ballpoint Pen - Black","uom":"pcs","active":true,"safety_stock":20,"target_stock":60},
    "suppliers": [{"supplier_id":"SUP-A","supplier_name":"Synthetic Supplier A","approved":true,"currency":"XTS"}],
    "commercial": [{"sku_id":"SKU-001","supplier_id":"SUP-A","approved_for_sku":true,"unit_price":"2.50","currency":"XTS","moq":50,"pack_multiple":10,"lead_time_days":2,"updated_at":"2026-09-27"}],
    "inventory": [{"sku_id":"SKU-001","on_hand":10,"snapshot_date":"2026-09-27"}],
    "demand": [{"sku_id":"SKU-001","quantity":30,"need_date":"2026-09-30"}],
    "open_po": []
  }
}
```

This example is synthetic. In the UI, retain the fetched context rather than replacing it with this example.
For missing inventory, supply exactly one confirmed snapshot; duplicate/conflicting inventory requires choosing the corrected authoritative row. A selected exception is not marked RESOLVED if its code/field remains present after evaluation. Other remaining problems remain BLOCKED and produce fresh exceptions. Context edits without a selected exception use the PATCH context endpoint. Both require the human credential.

Default-supplier changes are deliberate human corrections to the mapping, not supplier optimization or an arbitrary PO header override. Correct `commercial[0].supplier_id` and the approved supplier evidence using PATCH context; regenerate drafts. The old supplier draft loses that line and approval; the target supplier draft gains it and requires review. An empty old draft cannot be approved/exported.

## Line edits and review

```json
{"expected_version":3,"reason":"Human corrected order quantity","quantity":100,"unit_price":"2.5000"}
```

At least one of quantity/unit_price is required. MOQ and pack constraints still apply; amounts and totals are recomputed. The user may deliberately order a different positive quantity satisfying the commercial controls; this does not rewrite the engine recommendation. Both values remain visible in source evidence and audit history.

```json
{"expected_version":4,"confirm":true,"comment":"Reviewed price, quantities, and lead-time warnings"}
```

Every mutation changes the relevant version/revision. On `409 VERSION_CONFLICT`, refresh and review the new data. `401` means the Supabase token is missing, expired or invalid. `403 WORKSPACE_ACCESS_DENIED` means the user is not a member of the selected workspace; other 403 responses identify a missing workspace role. `409 APPROVAL_REQUIRED` and `409 FINANCE_APPROVAL_REQUIRED` prevent final export. `409 PO_AMOUNT_MISMATCH` blocks corrupted amounts. Critical edits clear both approvals.

## State semantics

- Run `CREATED` → `RUNNING` → `COMPLETED` or `NEEDS_ATTENTION`. These describe the scan, independently of PO approval.
- Every run contains one result per active SKU, initially BLOCKED with revision 0 / pending reason. Only evaluated results count as processed. After the full check, processed count equals expected count and each result is NO_REORDER, REORDER or BLOCKED.
- Draft `DRAFT` / `NEEDS_REVIEW` → Purchasing approval → `APPROVED`, or `FINANCE_REVIEW` when the workspace currency/threshold applies → Finance approval → `APPROVED`. Purchasing may reject; Finance may reject drafts awaiting Finance review. Source/critical changes clear both approvals and return to `NEEDS_REVIEW`.
- Exception OPEN → RESOLVED by an accepted correction, or SUPERSEDED by a later evaluation. History is retained.

Inspect `severity`: WARNING does not block a line, BLOCKING does. Show `decision_reason`, `evidence.timeline`, exception messages, and expected delivery dates to the reviewer. Do not calculate or infer approval state in the frontend.

Import parsing errors return 422. Validly parsed but structurally invalid datasets return a stored REJECTED import resource (201), with detailed issues; clients must inspect its status before continuing. Internal tool failures return 500, record FAILED where the database is available, and are never translated to a success report. After a failed Agent call, list runs and resume the created run rather than blindly creating another one.

Exports are saved as full immutable snapshots in approval/export history and returned as CSV; no filesystem path is supplied by the client. Draft GET provides a preview at any time. Export does not send orders, post inventory, or create live ERP transactions.
