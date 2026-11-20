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
    # Fallback to a local SQLite database for development/testing
    DATABASE_URL = "sqlite:///./dev.db"

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine_options = {
    "pool_pre_ping": True,
    "connect_args": {
        "sslmode": "require",
        # Supabase transaction poolers do not support prepared statements.
        "prepare_threshold": None,
    },
}
if os.getenv("VERCEL"):
    engine_options["poolclass"] = NullPool

if DATABASE_URL.startswith("sqlite"):
    # SQLite engine; no SSL or pool options needed
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
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
