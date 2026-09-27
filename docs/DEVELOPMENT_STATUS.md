# Development checkpoint

This commit saves the current work at the user's request before frontend development is complete.

## Backend

Implemented FastAPI, PostgreSQL/SQLAlchemy, Alembic, deterministic procurement calculations, import validation, exception correction, supplier-grouped PO drafts, explicit human approval, export and audit history. Synthetic fixtures and automated tests are included.

The original backend passed 55 PostgreSQL tests and migration checks (see `verification.md`). Subsequent frontend integration additions include read-only draft listing, synthetic demo scenarios, and a server-side agent message endpoint. DeepSeek is an optional intent parser; it does not perform procurement calculations or approvals. These additions still need dedicated integration tests.

## Frontend in progress

React + TypeScript + Vite source is included for the dashboard, data intake, SKU results, exception forms, PO review/approval, audit and compact agent panel. API calls target the real backend.

The UI stylesheet (`frontend/src/styles.css`) has not yet been implemented. Therefore the frontend is **not build-ready** in this checkpoint. Visual verification, browser end-to-end tests, and frontend setup documentation remain to be completed. This is a source backup, not a finished frontend release.

## Local-only files

The DeepSeek API key, `.env`, local databases, runtime outputs, virtual environments, node_modules and caches are excluded. No real provider key is required to build or test the deterministic backend. To configure DeepSeek on another machine, set `DEEPSEEK_API_KEY` on the backend or create the ignored local `deepseek_api_key.txt` file. Never put provider keys in frontend environment variables or source files.

## Next steps

1. Complete the frontend stylesheet and resolve any TypeScript/build errors.
2. Verify against the live backend and its OpenAPI schema.
3. Test all three demo stories and the full human approval workflow in a browser.
4. Add targeted tests for the new backend endpoints and run regression checks.
5. Update setup instructions and record final verification results.
