# Verification record

Updated 2026-09-28. Dataset and business values are synthetic.

| Check | Result |
| --- | --- |
| Python | CPython 3.12.13, project-local virtual environment |
| PostgreSQL | 16.15, isolated WSL instance on localhost:55432 |
| Full test suite on PostgreSQL | **85 passed**, including concurrent draft generation, SGD threshold boundaries and manager role isolation |
| SQLite tests | **84 passed**, PostgreSQL-only row-lock test skipped |
| Static checks | `ruff check backend tests migrations agent.py` passed |
| Alembic | SQLite upgrade → downgrade → upgrade passed; existing PostgreSQL demo upgrade and schema check passed |
| Schema drift | `alembic check`: no new upgrade operations |
| HTTP adapters | JSON, six CSVs, six-sheet XLSX through FastAPI tested |
| Original Biz templates | Placeholder lead time normalized; missing commercial data blocked |
| Real HTTP server | `/health` ok, `/ready` ready, `/openapi.json` returned successfully |
| Demo run | 10 processed / 6 REORDER / 1 NO_REORDER / 3 BLOCKED |
| Docker image | Configuration supplied; build not executed because local Docker engine was unavailable |
| Frontend production build | TypeScript check and Vite build passed |
| Browser workflows | **13 workflows**, including manual data entry → SGD 5,000 PO → Purchasing approval → Finance approval → export, immutable batch editing, duplication/deletion, chat navigation/history, all previous procurement workflows and mobile layout |
| Visual inspection | Desktop 1440px and mobile 390px screenshots inspected; mobile overflow check passed |
| DeepSeek provider | Tool loop, failure handling, private-reasoning isolation and free-form routing tested with mocks; real provider smoke test completed in the preceding chatbot upgrade |

Backend tests create/drop their own tables and require a PostgreSQL database name ending `_test`. This revision's browser tests use an isolated `.runtime` SQLite database and production assets on port 8010. Chat-provider responses are mocked in the navigation/history browser test. No external orders are sent. The browser profile is display-only; role-specific backend credentials grant access.

There is one upstream Starlette TestClient deprecation warning about its httpx adapter; tests currently pass. No warning is suppressed.

Use the README startup instructions and an explicit DATABASE_URL; Compose uses port 5432. Upgrade existing installations with `alembic upgrade head`. Existing SGD approvals of 5,000 or above enter `FINANCE_REVIEW` and require Finance approval before export.

Runtime caches, provider keys, generated builds and browser reports are ignored by Git. The source business documents remain unchanged. The outdated generated demo run report and duplicate development-status document were removed; this file is the single verification record.
