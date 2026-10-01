# Procurement workspace frontend

React + TypeScript + Vite, connected to FastAPI. Includes a product landing page, Supabase business login/registration, persistent username/password Demo accounts, and a hover-expand enterprise workspace shell. Demo registration requires no email, phone or verification; passwords are hashed by the backend and never stored in the browser.

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

The hosted frontend connects automatically after Supabase sign-in. An optional **API connection** panel remains available under Account for administrators and legacy deployments; keys are editable, masked, and kept only in the current browser tab. API-key mode requires the backend administrator to enable `ALLOW_API_KEYS`. Local development starts with the explicit demo credentials from `.env.example`. DeepSeek credentials are read only by the backend from `DEEPSEEK_API_KEY` or the ignored root `deepseek_api_key.txt`.

## Demo walkthrough

1. Run the normal demo. Review SKU evidence and supplier drafts. Approval requires a confirmation checkbox and comment; approved drafts support CSV download.
2. Run the incoming-stock demo. Timely incoming stock prevents an unnecessary purchase; late incoming stock leaves a timing gap visible.
3. Run the exceptions demo. All 10 SKUs are scanned while 3 decisions remain blocked. Correct missing price, missing inventory and supplier approval through the forms, then review updated drafts. Editing an approved draft requires approval again.

The data page accepts files or manual input through **Build dataset manually**. Add, edit, duplicate and delete records across all six tables. **Edit as new batch** also repairs rejected imports while retaining the original version. Saving and validating opens the review policy form; the resulting run is available to the Agent. SGD drafts of 5,000 or above require Finance Manager approval after Purchasing Manager approval.

## Verification

```powershell
npm run build
$env:FRONTEND_URL='http://127.0.0.1:8000'
npm run test:e2e
```

Tests require the backend, database and frontend running with default demo credentials. They create synthetic runs and approved drafts; use a development database. Windows uses installed Microsoft Edge. On other platforms install Chromium using `node node_modules/@playwright/test/cli.js install chromium`.

See [verification](../docs/verification.md) for current test results and environment limits. The browser suite covers manual entry through dual approval and export, versioned edits, chat history/navigation, cockpit simulation, exception correction, and mobile layout. Fonts are bundled locally.
