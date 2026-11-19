import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

if __package__:
    from .models import Base
else:
    from models import Base

DB_PATH = Path(__file__).resolve().with_name("telemetria.db")
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
else:
    DATABASE_URL = f"sqlite:///{DB_PATH}"

engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite:"):
    engine_options["connect_args"] = {"check_same_thread": False}
else:
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
