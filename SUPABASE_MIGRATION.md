# Supabase PostgreSQL

The application requires Supabase PostgreSQL through `DATABASE_URL`. It does
not create, read, or write a local SQLite database. If `DATABASE_URL` is
missing, the backend stops with a configuration error.

## Configure Supabase

1. In the Supabase project, open **SQL Editor** and run
   `supabase/migrations/20261119000100_create_telemetry_tables.sql`.
2. In Supabase **Connect**, copy the **Transaction pooler** URI (port `6543`).
   URL-encode special characters in the password and keep the URI secret.
3. Set the URI as `DATABASE_URL` in your local environment or Vercel project.
   The backend accepts `postgresql://` and `postgres://` URIs and enables SSL.
4. Restart or redeploy the application. Its FastAPI startup will verify/create
   the ORM tables against PostgreSQL.

The migration creates `telemetria`, `archivos_cargados`, and `upload_chunks`.
The upload endpoint uses PostgreSQL staging rows to assemble files across
separate Vercel function invocations.

## Vercel API routes

Set the Vercel project's **Root Directory** to the repository root (`.`), then
add `DATABASE_URL` to its environment variables and redeploy. The root
`pyproject.toml` configures Vercel to serve `backend.main:app` and build the
frontend. The Vercel function's local filesystem is temporary, so persistent
application data belongs in Supabase.
