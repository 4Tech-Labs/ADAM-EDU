import os

import pytest

from shared.database import SessionLocal, engine
from shared.models import Base


@pytest.fixture(scope="session", autouse=True)
def ensure_db_schema() -> None:
    """Create the ORM schema once so the suite can run against an empty database."""
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def db(ensure_db_schema: None):
    """Provide a real SQLAlchemy session for API tests."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip live LLM tests unless they are explicitly enabled."""
    run_live = os.getenv("RUN_LIVE_LLM_TESTS") == "1"
    has_gemini_key = bool(os.getenv("GEMINI_API_KEY"))

    skip_live = pytest.mark.skip(reason="Set RUN_LIVE_LLM_TESTS=1 to run live Gemini tests.")
    skip_missing_key = pytest.mark.skip(reason="GEMINI_API_KEY is required for live Gemini tests.")

    for item in items:
        if "live_llm" not in item.keywords:
            continue
        if not run_live:
            item.add_marker(skip_live)
        elif not has_gemini_key:
            item.add_marker(skip_missing_key)
