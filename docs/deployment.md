# GitHub Pages + Render + Supabase

Frontend URL: https://ruiyifan0114-design.github.io/Agent-for-SME-purchase-order-preparation-/

GitHub Pages serves only the frontend. FastAPI runs on Render and connects to Supabase PostgreSQL. A local computer is not needed after all three services are configured.

## 1. Supabase

Create a dedicated project. Enable email/password authentication, set the Site URL to the GitHub Pages URL above, and add that same URL to Auth redirect URLs. In Connect, copy the **Session pooler** PostgreSQL URI (port 5432, IPv4 compatible). Use this format in the backend's DATABASE_URL:

```text
postgresql+psycopg://postgres.PROJECT_REF:URL_ENCODED_PASSWORD@POOLER_HOST:5432/postgres?sslmode=require
```

URL-encode special characters in the password. Do not use the Supabase public API URL, anon key, or transaction pooler for this configuration. Use a dedicated database and disable the Supabase Data API if unused: procurement tables are accessed only through FastAPI. Do not expose these tables through unauthenticated Supabase API access.

## 2. Render

Create a Blueprint from this repository using [Render](https://dashboard.render.com/select-repo?type=blueprint). The root `render.yaml` supplies the Docker service, Singapore region and health check.

Enter DATABASE_URL and DEEPSEEK_API_KEY in Render's private environment settings. `SUPABASE_URL` identifies the token issuer and `ALLOW_API_KEYS=false` disables shared application keys in production. The DeepSeek key belongs only on the backend. Check the model value against your provider account if needed.

The container applies Alembic migrations before starting. The migrations revoke the Supabase `anon` and `authenticated` roles from procurement tables, sequences and functions, including default privileges for future objects. Wait for `/ready` to return HTTP 200. Copy the actual assigned `https://...onrender.com` origin. The free plan can sleep when idle; the first request may take longer. This deployment creates empty cloud tables; it does not copy local procurement records. Import data through Data intake.

## 3. GitHub Pages

In repository Settings → Pages, select GitHub Actions. In Settings → Secrets and variables → Actions → Variables, add **VITE_API_BASE_URL** with the Render HTTPS origin (without `/api/v1`), **VITE_SUPABASE_URL**, and the project's **VITE_SUPABASE_PUBLISHABLE_KEY**. Run **Deploy frontend to GitHub Pages** again after setting or changing a variable. Main-branch pushes deploy automatically.

The Vite base path matches the repository subpath and navigation uses hash routes. A Supabase publishable key is designed for browser use; the database password, DeepSeek key and service-role key must never be placed in GitHub Pages variables or any `VITE_*` value. Until the required public variables are configured, the landing page remains available in local-demo mode.

## 4. Access and verification

Open the Pages site and create or sign into an individual Supabase account. The first authenticated user can create an organization and warehouse workspace. Owners can then invite verified email addresses and assign procurement, purchasing, finance or viewer roles. Switching the sidebar workspace changes the `X-Workspace-ID`; the API independently verifies membership on every request.

Verify an import, run, chatbot question, draft and two-stage approval. Check browser requests target the Render HTTPS origin and CORS allows `https://ruiyifan0114-design.github.io`. Do not include the repository path in CORS_ORIGINS.

For Railway instead, deploy the Dockerfile, set the same environment variables, generate three distinct private role keys, and enable a public HTTPS domain. The container respects the platform PORT variable.

References: [Vite Pages deployment](https://vite.dev/guide/static-deploy#github-pages), [Render Blueprint](https://render.com/docs/blueprint-spec), [Supabase connections](https://supabase.com/docs/guides/database/connecting-to-postgres).
