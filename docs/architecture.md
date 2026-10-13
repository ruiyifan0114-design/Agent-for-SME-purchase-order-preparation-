# Production foundation architecture

The deterministic domain engine remains the authority for quantities, dates and amounts. A run freezes its normalized SKU context, `rule_version`, `rules_snapshot` and `approval_policy_snapshot`; later workspace policy changes cannot alter historical decisions or approval gates.

External systems implement `ProcurementSourceAdapter` and return a `SourceEnvelope`. CSV, JSON and mock ERP adapters currently use that boundary. The envelope records `source_system`, `external_id`, `synced_at` and source metadata. A future ERP/WMS/MRP connector should fetch remotely with bounded retry, then perform one local idempotent write. Ambiguous remote writes must not be retried automatically.

`JobRecord` is a durable scheduler boundary. The existing synchronous endpoints remain for compatibility; production workers can create and execute `import_dataset`, `procurement_check` and `generate_po_drafts` jobs through the job API. Idempotency keys prevent duplicate job creation. This avoids requiring Redis or Celery on the current single-service Render deployment while leaving a clean worker seam.

Authorization is enforced in FastAPI dependencies and again for human approval operations. Existing workspace roles remain compatible; `admin`, `procurement_user` and `approver` are accepted service-level aliases while the current UI continues to use owner/procurement/purchasing/finance/viewer.

HTTP responses include `X-Correlation-ID`. Structured request logs and audit rows contain action, actor, user, workspace correlation and duration. `/health` checks process liveness, `/ready` checks database/migration access, and `/metrics` exposes lightweight process counters suitable for scraping on the current deployment.
