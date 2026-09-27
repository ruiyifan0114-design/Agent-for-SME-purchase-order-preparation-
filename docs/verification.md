# Verification record

Date: 2026-09-27. Dataset and business values are synthetic.

| Check | Result |
| --- | --- |
| Python | CPython 3.12.13, project-local virtual environment |
| PostgreSQL | 16.15, isolated WSL instance on localhost:55432 |
| Full test suite on PostgreSQL | **55 passed**, including simultaneous draft generation |
| Static checks | `ruff check backend tests migrations agent.py` passed |
| Alembic | upgrade → check → downgrade → upgrade passed against PostgreSQL |
| Schema drift | `alembic check`: no new upgrade operations |
| HTTP adapters | JSON, six CSVs, six-sheet XLSX through FastAPI tested |
| Original Biz templates | Placeholder lead time normalized; missing commercial data blocked |
| Real HTTP server | `/health` ok, `/ready` ready, `/openapi.json` returned successfully |
| Demo run | 10 processed / 6 REORDER / 1 NO_REORDER / 3 BLOCKED |
| Docker image | Configuration supplied; build not executed because local Docker engine was unavailable |

The PostgreSQL test database was separate from the seeded demo database. Tests create/drop their own tables and require a database name ending `_test`. No external procurement orders were approved or sent. Test approval requests used synthetic fixtures and the test reviewer identity; the seeded demo retains unapproved drafts.

There is one upstream Starlette TestClient deprecation warning about its httpx adapter; tests currently pass. No warning is suppressed.

The temporary verification server was started at `http://127.0.0.1:8000` with the demo database on port 55432. These running processes are a local preview, not deployment or automatic startup services. For repeatable startup use the README instructions and an explicit DATABASE_URL; the supplied Compose configuration uses port 5432.
