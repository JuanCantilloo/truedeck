"""Copy the local SQLite telemetry database into an empty PostgreSQL database.

Required environment:
  DATABASE_URL  PostgreSQL/Supabase connection URI (kept out of source control)
Optional environment:
  SQLITE_PATH   SQLite source file (defaults to backend/telemetria.db)
  BATCH_SIZE    Rows copied per batch (defaults to 10000)
"""

import os
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, func, select, text


ROOT_DIR = Path(__file__).resolve().parents[1]
SQLITE_PATH = Path(os.getenv("SQLITE_PATH", ROOT_DIR / "backend" / "telemetria.db"))
BATCH_SIZE = max(1, int(os.getenv("BATCH_SIZE", "10000")))
TABLE_NAMES = ("telemetria", "archivos_cargados")


def normalize_postgres_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def main() -> None:
    target_url = os.getenv("DATABASE_URL")
    if not target_url:
        raise SystemExit("Define DATABASE_URL con la conexión PostgreSQL de destino.")
    if not SQLITE_PATH.is_file():
        raise SystemExit(f"No existe la SQLite de origen: {SQLITE_PATH}")

    source_engine = create_engine(f"sqlite:///{SQLITE_PATH}")
    target_engine = create_engine(normalize_postgres_url(target_url), pool_pre_ping=True)
    source_metadata = MetaData()
    target_metadata = MetaData()
    source_metadata.reflect(bind=source_engine, only=TABLE_NAMES)
    target_metadata.reflect(bind=target_engine, schema="public", only=TABLE_NAMES)

    missing = [name for name in TABLE_NAMES if name not in source_metadata.tables]
    if missing:
        raise SystemExit(f"Faltan tablas en SQLite: {', '.join(missing)}")

    source_tables = {name: source_metadata.tables[name] for name in TABLE_NAMES}
    target_tables = {
        name: target_metadata.tables[f"public.{name}"] for name in TABLE_NAMES
    }

    copied = {}
    with source_engine.connect() as source, target_engine.begin() as target:
        for name in TABLE_NAMES:
            destination = target_tables[name]
            existing = target.execute(
                select(func.count()).select_from(destination)
            ).scalar_one()
            if existing:
                raise SystemExit(
                    f"La tabla public.{name} ya tiene {existing} filas. "
                    "La migración requiere tablas de destino vacías para evitar duplicados."
                )

        for name in TABLE_NAMES:
            source_table = source_tables[name]
            target_table = target_tables[name]
            result = source.execution_options(stream_results=True).execute(
                select(source_table)
            )
            row_count = 0
            while rows := result.mappings().fetchmany(BATCH_SIZE):
                target.execute(target_table.insert(), [dict(row) for row in rows])
                row_count += len(rows)
            copied[name] = row_count

            # Explicit IDs are copied, so advance each PostgreSQL identity sequence.
            target.execute(text(
                f"""select setval(
                    pg_get_serial_sequence('public.{name}', 'id'),
                    coalesce(max(id), 1),
                    max(id) is not null
                ) from public.{name}"""
            ))

    source_engine.dispose()
    target_engine.dispose()
    for name, count in copied.items():
        print(f"public.{name}: {count:,} filas copiadas")
    print("Migración terminada.")


if __name__ == "__main__":
    main()
