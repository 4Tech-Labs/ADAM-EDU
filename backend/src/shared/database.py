from collections.abc import Generator
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

class Settings(BaseSettings):
    """
    Configuration settings for the database connection.
    In local/dev environments this may load from a .env file.
    In production (Cloud Run), these should be injected either by Secret Manager
    or environment variables mapped to Secret Manager.
    """
    # Single source of truth for the connection string
    database_url: str
    
    # Connection Pooling limits to protect Cloud SQL from Serverless horizontal scaling exhaustion
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800 # Recycle connections after 30 minutes

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore")

settings = Settings()

# Create the SQLAlchemy Engine with strict pooling settings for Cloud Run
engine = create_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    # pool_pre_ping=True verifies connection liveness before usage, essential for serverless
    pool_pre_ping=True, 
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""

    pass

def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI endpoints to yield a database session
    and ensure it is closed after the request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
