"""
Pytest fixtures shared across all test modules.
"""
from __future__ import annotations

import os
import sys
import sqlite3
import tempfile
import pytest
from pathlib import Path

# Ensure project root is on sys.path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Database fixture ──────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Provide a fresh in-memory SQLite DB for each test."""
    db_file = str(tmp_path / "test.db")
    monkeypatch.setenv("TEST_DB_PATH", db_file)

    import backend.database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    db_mod.init_db()

    yield db_file


# ── FastAPI test client ───────────────────────────────────────────────────────

@pytest.fixture
def api_client(tmp_db):
    """Return a FastAPI TestClient with a fresh database."""
    from fastapi.testclient import TestClient

    # Prevent the pipeline from actually starting in tests
    os.environ.setdefault("THREATSENSE_NO_PIPELINE", "1")
    os.environ.setdefault("JWT_SECRET", "test-secret-key-for-tests-only")

    from backend.main import app
    with TestClient(app) as client:
        yield client


# ── Auth helpers ──────────────────────────────────────────────────────────────

@pytest.fixture
def admin_token(api_client):
    """Log in as admin and return a JWT token."""
    resp = api_client.post("/api/login", json={
        "username": os.environ.get("ADMIN_USERNAME", "admin"),
        "password": os.environ.get("ADMIN_PASSWORD", ""),
    })
    if resp.status_code != 200:
        pytest.skip("Admin login failed — set ADMIN_PASSWORD env var or seed DB first")
    return resp.json()["token"]


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}
