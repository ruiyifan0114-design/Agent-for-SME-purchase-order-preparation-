# Verification record

Date: 2026-09-27. Dataset and business values are synthetic.

| Check | Result |
| --- | --- |
| Python | CPython 3.12.13, project-local virtual environment |
| PostgreSQL | 16.15, isolated WSL instance on localhost:55432 |
| Full test suite on PostgreSQL | **70 passed**, including simultaneous draft generation and frontend integration endpoints |
| Static checks | `ruff check backend tests migrations agent.py` passed |
| Alembic | upgrade → check → downgrade → upgrade passed against PostgreSQL |
| Schema drift | `alembic check`: no new upgrade operations |
| HTTP adapters | JSON, six CSVs, six-sheet XLSX through FastAPI tested |
| Original Biz templates | Placeholder lead time normalized; missing commercial data blocked |
| Real HTTP server | `/health` ok, `/ready` ready, `/openapi.json` returned successfully |
| Demo run | 10 processed / 6 REORDER / 1 NO_REORDER / 3 BLOCKED |
| Docker image | Configuration supplied; build not executed because local Docker engine was unavailable |
| Frontend production build | TypeScript check and Vite build passed |
| Browser workflows | **9 passed**, Edge, production assets served on port 8000 with real API |
| Visual inspection | Desktop 1440px and mobile 390px screenshots inspected; mobile overflow check passed |
| DeepSeek provider | Failure and untrusted model output tested with stubs; live paid provider not called |

The PostgreSQL test database was separate from the seeded demo database. Backend tests create/drop their own tables and require a database name ending `_test`. Browser tests create additional synthetic records in the local demo database, including approved and rejected test drafts. No external procurement orders were sent.

There is one upstream Starlette TestClient deprecation warning about its httpx adapter; tests currently pass. No warning is suppressed.

The temporary verification server was started at `http://127.0.0.1:8000` with the demo database on port 55432. These running processes are a local preview, not deployment or automatic startup services. For repeatable startup use the README instructions and an explicit DATABASE_URL; the supplied Compose configuration uses port 5432.
