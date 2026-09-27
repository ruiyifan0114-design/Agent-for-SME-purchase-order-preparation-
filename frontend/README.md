# Procurement workspace frontend

React + TypeScript + Vite, connected to the real FastAPI backend.

## Start

Start PostgreSQL, configure the root `.env`, run migrations and start FastAPI on port 8000 using the root README. With Node.js 22 available:

```powershell
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Vite proxies API requests to port 8000. Scripts invoke Node directly so Windows paths containing `&` work.

For a single-origin preview, run `npm run build`, then start or restart FastAPI. Open http://127.0.0.1:8000. FastAPI mounts `frontend/dist` at startup. Hash routes preserve navigation on reload. Root Docker Compose also builds the frontend into the API image; that image build is not locally verified.

## Credentials

Connection settings accept service and reviewer credentials, stored in sessionStorage for the browser tab. Defaults match `.env.example`; update settings if the backend credentials change. DeepSeek credentials are read only by the backend from `DEEPSEEK_API_KEY` or the ignored root `deepseek_api_key.txt`. Do not put provider credentials in Vite variables.

## Demo walkthrough

1. Run the normal demo. Review SKU evidence and supplier drafts. Approval requires a confirmation checkbox and comment; approved drafts support CSV download.
2. Run the incoming-stock demo. Timely incoming stock prevents an unnecessary purchase; late incoming stock leaves a timing gap visible.
3. Run the exceptions demo. All 10 SKUs are scanned while 3 decisions remain blocked. Correct missing price, missing inventory and supplier approval through the forms, then review updated drafts. Editing an approved draft requires approval again.

The data page accepts six CSV files, a six-sheet XLSX workbook or JSON. Validation findings and rejected imports remain visible. Interrupted checks resume the existing run. The agent explains saved decisions and opens proposed correction forms; it cannot silently save corrections or approve orders.

## Verification

```powershell
npm run build
$env:FRONTEND_URL='http://127.0.0.1:8000'
npm run test:e2e
```

Tests require the backend, database and frontend running with default demo credentials. They create synthetic runs and approved drafts; use a development database. Windows uses installed Microsoft Edge. On other platforms install Chromium using `node node_modules/@playwright/test/cli.js install chromium`.

All nine browser workflows passed against the production build: approval/export/reapproval/rejection, incoming stock, three blocker corrections, agent suggestions without silent writes, failed approval, CSV validation, mobile layout, scan resumption and rejected JSON intake. Fonts are bundled locally. See [verification](../docs/verification.md) for backend checks and environment limitations.
