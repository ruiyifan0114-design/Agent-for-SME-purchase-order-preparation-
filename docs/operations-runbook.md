# Operations runbook

## Deploy and migrate

1. Back up the database and record the current application commit and Alembic revision.
2. Deploy code with backend-only environment variables from `.env.example`.
3. Run `alembic upgrade head` once as a release step.
4. Verify `/health`, `/ready`, authentication, one read-only workspace request, and one synthetic procurement run.
5. Roll back application code first if runtime verification fails. Downgrade the database only after reviewing the migration and taking another backup; schema downgrade can discard new rule, provenance and job data.

## Supabase backup and restore

Use the backup/PITR capability available on the project's actual Supabase plan. Do not assume PITR is enabled. Before a high-risk release, create a logical backup with `pg_dump` using a server-side secret and test restoration into a separate database with `pg_restore`. Never test a restore over production. Record backup time, source revision, restore duration and row-count checks for workspace, import, run, result, draft and audit tables.

## Recovery

- Stop writers or put the API in maintenance mode.
- Preserve logs, correlation IDs and the failed job record.
- Restore into a separate database, run `alembic current`, and validate tenant row counts and representative historical run snapshots.
- Point a staging API at the restored database and run smoke tests before changing production `DATABASE_URL`.
- Re-run only idempotent jobs. Do not blindly repeat approval, export or external write operations.

## Secrets requiring rotation

Credentials previously pasted into chat or stored in the removed local DeepSeek key file must be treated as exposed. Rotate the DeepSeek key, all legacy API/reviewer/finance keys, and the previously shared PostgreSQL password. Update Render/Supabase secrets, invalidate the old values, and keep `ALLOW_API_KEYS=false` for the hosted service. No database, Supabase service-role or LLM secret may use a `VITE_`/`NEXT_PUBLIC_` variable.

## Job handling

Jobs are persisted with PENDING/RUNNING/SUCCEEDED/FAILED state. Run `python -m backend.jobs.worker --once` from a scheduler, or omit `--once` for a separately managed worker process. PostgreSQL uses `FOR UPDATE SKIP LOCKED` while claiming work. The HTTP execute endpoint remains for backward compatibility and returns an already-running job without executing it again. Failed ambiguous writes require human reconciliation before retry.
