# PostgreSQL / Supabase

The backend uses `DATABASE_URL` when set. Without it, local development keeps
using `backend/telemetria.db` (SQLite).

## Create the Supabase schema

1. Create a Supabase project.
2. Run `supabase/migrations/20261119000100_create_telemetry_tables.sql` in the
   Supabase SQL Editor, or apply it with the Supabase CLI.
3. Copy the PostgreSQL URI from **Project Settings → Database → Connection
   string**. Use the pooled URI for serverless deployments and keep its
   password private.
4. Set `DATABASE_URL` in the backend's environment. The backend understands
   both `postgresql://` and `postgres://` Supabase URIs.

The migration creates `upload_chunks` as temporary staging storage. The upload
API deletes those rows after processing each file; storing chunks in PostgreSQL
lets Vercel assemble uploads across separate function invocations.

## Copy the current local SQLite data

The migration script copies rows from the local SQLite file to empty PostgreSQL
tables in batches and resets the identity sequences afterward:

```sh
python -m pip install -r requirements.txt
DATABASE_URL='postgresql://…' python backend/migrate_sqlite_to_postgres.py
```

Set `SQLITE_PATH` if the source file is somewhere other than
`backend/telemetria.db`. The script refuses to write into non-empty target
tables so it cannot silently duplicate records.

## Vercel API routes

To deploy the FastAPI API and Vite frontend in the same Vercel project, set that
project's **Root Directory** to the repository root (`.`), then redeploy. The
root `pyproject.toml` points Vercel to `backend.main:app` and runs the frontend
build. Add `DATABASE_URL` to the Vercel project's environment variables.

The Vercel function's local filesystem is temporary; use Supabase/PostgreSQL
for database records. The upload endpoint sends chunks under Vercel's function
request-size limit.
