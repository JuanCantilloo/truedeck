import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

if __package__:
    from .models import Base
else:
    from models import Base

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is required. Configure a PostgreSQL connection to Supabase."
    )

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine_options = {"pool_pre_ping": True}
engine_options["connect_args"] = {
    "sslmode": "require",
    # Supabase's transaction pooler does not support prepared statements.
    "prepare_threshold": None,
}
# The backend runs as a serverless function on Vercel; avoid keeping a
# process-local pool of connections alive between short invocations.
if os.getenv("VERCEL"):
    engine_options["poolclass"] = NullPool

engine = create_engine(DATABASE_URL, **engine_options)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
