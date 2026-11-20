import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

if __package__:
    from .models import Base
else:
    from models import Base

# Use the operating system's temporary directory by default. On Vercel, this
# file exists only in a function instance and disappears when Vercel recycles
# that instance. Local development can override it with SQLITE_PATH.
default_db_path = Path("/tmp/truedeck/telemetria.db")
DB_PATH = Path(os.getenv("SQLITE_PATH", str(default_db_path))).expanduser()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
