import os
import pathlib

import pytest
from fastapi.testclient import TestClient

TEST_DB_FILE = pathlib.Path(__file__).resolve().parent.parent / "test_archai.db"
TEST_DB_PATH = "sqlite:///./test_archai.db"
os.environ["ARCHAI_DATABASE_URL"] = TEST_DB_PATH
os.environ["ARCHAI_OLLAMA_ENABLED"] = "false"

# Start every run from an empty database. Nothing deleted this file, so it kept
# every workspace any run had ever created: at 2,933 workspaces and 1.7 GB, the
# list endpoint — which loads and repairs each workspace it returns — made the
# suite crawl and then get killed for memory, which looks exactly like a
# hanging test. Removing the file here costs nothing: the schema is recreated
# on import below, and no test depends on another run's data.
if TEST_DB_FILE.exists():
    TEST_DB_FILE.unlink()
for suffix in ("-wal", "-shm"):
    sidecar = TEST_DB_FILE.with_name(TEST_DB_FILE.name + suffix)
    if sidecar.exists():
        sidecar.unlink()

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session():
    """A direct session, for tests that need to simulate stored state.

    Used to write a pre-upgrade artifact into a workspace row so the read-path
    repair can be exercised the way a real older project would exercise it.
    """
    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
