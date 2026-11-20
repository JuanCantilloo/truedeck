# Supabase PostgreSQL

The backend uses Supabase PostgreSQL through the `DATABASE_URL` environment
variable. It no longer falls back to SQLite. The schema migration is in
`supabase/migrations/20261119000100_create_telemetry_tables.sql`.

## Configure the connection

1. In Supabase, open **Connect → Transaction pooler** and copy the URI on port
   `6543`. Use the pooler username shown by Supabase.
2. URL-encode reserved characters in the database password and keep the URI
   secret.
3. In Vercel, open **Settings → Environment Variables** and add:
   - **Name:** `DATABASE_URL`
   - **Value:** the Supabase Transaction pooler URI
   - Select **Production**, **Preview**, and/or **Development** as needed.
4. Redeploy so the function receives the variable.

Only `DATABASE_URL` is required. The backend uses SQLAlchemy with the psycopg
driver, requires SSL, and disables prepared statements for compatibility with
Supabase's transaction pooler. Do not put the URI in frontend code or commit it
to GitHub.

## Apply the schema

The current Supabase project already has the schema and migrated rows. For a
new project, run `supabase/migrations/20261119000100_create_telemetry_tables.sql`
in the Supabase SQL Editor before deploying. The backend also creates ORM
tables on startup if they are missing.

## Vercel project settings

- Set **Root Directory** to the repository root (leave the field empty).
- Keep **Include files outside the root directory** enabled if the dashboard
  requires it.
- Clear **Output Directory** overrides such as `dist` or `frontend/dist`.
- Deploy the latest commit. The root `app.py` exposes the FastAPI app; the
  root `requirements.txt` and `frontend/requirements.txt` both include the
  Python dependencies so either project root can install them.
- Verify `/api/health` on the deployment domain returns `{"status":"ok"}`.
