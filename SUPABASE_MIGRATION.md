# Vercel and temporary SQLite

The application now uses SQLite instead of Supabase. On Vercel, the database
file is placed under `/tmp/truedeck/telemetria.db`, which belongs to a
temporary function instance and is removed when Vercel recycles that instance.
No `DATABASE_URL` is required. Local development uses the same temporary path
unless `SQLITE_PATH` is set.

## Vercel project settings

- Set **Root Directory** to the repository root (`.`).
- Clear **Output Directory** if it points to `dist` or `frontend/dist`.
- Redeploy the latest commit. The root `app.py` exposes the FastAPI app and
  `pyproject.toml` builds the frontend into `frontend/dist`.
- Verify `https://<deployment-domain>/api/health` returns `{"status":"ok"}`.

Small files (up to 3 MiB) are sent in one request. Larger files are split into
requests and staged in SQLite. Because Vercel's temporary filesystem is local
to each function instance, a large upload can fail if its requests land on
different instances. Reliable large-file uploads require shared temporary
storage, such as Supabase or object storage.

The previous Supabase migration SQL remains in `supabase/migrations/` for
reference; the application no longer reads or writes those tables.
