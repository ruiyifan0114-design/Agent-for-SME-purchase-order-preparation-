# Intentionally out-of-scope production risks

- No live ERP/WMS/MRP connector, webhook verification or vendor-specific reconciliation yet.
- The durable job table has a runnable worker and PostgreSQL claim locking, but no lease/heartbeat or managed queue. A worker killed after claiming a job leaves it RUNNING for manual reconciliation.
- Metrics are in-process counters; production aggregation, dashboards, traces and alert routing remain external work.
- Enterprise SSO, MFA policy enforcement, SCIM, formal access reviews and field-level masking are not implemented.
- No SOC 2/ISO 27001 certification, penetration test or formal threat model has been completed.
- Procurement remains one warehouse and one base policy currency per run. An explicitly saved sourcing decision can generate split supplier drafts; unconstrained network-wide optimization across warehouses remains out of scope.
- Budget dimensions, tax/duty/freight calculation, receipts and invoice matching now have a deterministic foundation; reservation accounting, general-ledger journals and ERP PO transmission remain out of scope.
- FX rates must be supplied and snapshotted by an authorized source; there is no market-rate provider or silent current-rate lookup.
- PostgreSQL concurrency tests require a disposable `TEST_DATABASE_URL`; SQLite tests cannot prove production locking behavior.
- Backup/PITR availability depends on the selected Supabase plan and must be verified operationally.
- Stored inventory policies are frozen and applied to run evaluation; effective agreements and supplier performance are frozen and applied when sourcing is explicitly requested. Automatic multi-supplier sourcing during the daily scan is not enabled; the simple imported workflow stays the default.
- Advanced sourcing is explicitly requested through an API. Full management screens for supplier agreements, policy configuration and matrix delegation are not yet provided.
- Invoice matching tolerances are administrator-configured and frozen per run. Credit-note and invoice reconciliation workflows are still required before finance production use.
- The worker command must be deployed as a separately managed process or invoked by a scheduler; the current free Render web service does not start it automatically.
