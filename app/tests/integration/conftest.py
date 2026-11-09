"""Fixtures for integration tests: real Postgres (production schema + grants) and a GCS emulator.

Start the backends first, from app/:
    docker compose -f docker-compose.it.yml up -d --wait
Each test gets freshly created tables and its own bucket, so tests don't depend on each other.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage

from file_service.auth import hash_password
from file_service.repository import PostgresRepository
from file_service.storage import GCSStorage

ADMIN_DSN = os.getenv("FS_IT_ADMIN_DSN", "postgresql://postgres:postgres@localhost:55432/files")
APP_DSN = os.getenv("FS_IT_APP_DSN", "postgresql://it_app:it-app-password@localhost:55432/files")
GCS_ENDPOINT = os.getenv("FS_IT_GCS_ENDPOINT", "http://localhost:4443")
SCHEMA_SQL = Path(__file__).resolve().parents[2] / "db" / "schema.sql"
START_HINT = "start the backends from app/ with: docker compose -f docker-compose.it.yml up -d --wait"

# The app logs in as `it_app`, which only gets privileges through `file_service_app`
# (created by schema.sql) - exactly how the Cloud SQL IAM user gets them in GCP.
APP_ROLE_SQL = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'it_app') THEN
    CREATE ROLE it_app LOGIN PASSWORD 'it-app-password';
  END IF;
END
$$;
GRANT file_service_app TO it_app;
"""


@dataclass
class Seed:
    """Test data written with admin rights, the way the upload service / an operator would."""

    db: asyncpg.Connection
    bucket: storage.Bucket

    async def user(self, username: str, customer_id: str, password: str) -> None:
        await self.db.execute(
            "INSERT INTO users (username, customer_id, password_hash) VALUES ($1, $2, $3)",
            username, customer_id, hash_password(password))

    async def file(self, customer_id: str, file_id: str, content: bytes = b"", *, status: str = "available",
                   age_seconds: int = 0, size_bytes: int | None = None, filename: str | None = None) -> str:
        """Insert a metadata row; upload `content` to the bucket if non-empty."""
        object_key = f"{customer_id}/{file_id}"
        if content:
            self.bucket.blob(object_key).upload_from_string(content)
        await self.db.execute(
            "INSERT INTO files (customer_id, file_id, object_key, filename, content_type, size_bytes, status, "
            "created_at) VALUES ($1, $2, $3, $4, 'text/plain', $5, $6, $7)",
            customer_id, file_id, object_key, filename or f"{file_id}.txt",
            len(content) if size_bytes is None else size_bytes, status,
            datetime.now(UTC) - timedelta(seconds=age_seconds))
        return object_key


@pytest.fixture
async def db():
    """Admin connection; recreates the schema so every test starts empty."""
    try:
        conn = await asyncpg.connect(ADMIN_DSN, timeout=5)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.fail(f"Postgres not reachable at {ADMIN_DSN} ({exc}); {START_HINT}", pytrace=False)
    try:
        await conn.execute("DROP TABLE IF EXISTS sessions, users, files CASCADE")
        await conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        await conn.execute(APP_ROLE_SQL)
        yield conn
    finally:
        await conn.close()


@pytest.fixture
def app_dsn(db) -> str:
    """DSN of the least-privilege app login (depends on `db` so the schema exists first)."""
    return APP_DSN


@pytest.fixture
async def app_conn(app_dsn):
    conn = await asyncpg.connect(app_dsn, timeout=5)
    yield conn
    await conn.close()


@pytest.fixture
async def repo(app_dsn):
    repository = await PostgresRepository.create(app_dsn, 1, 4)
    yield repository
    await repository.close()


@pytest.fixture
def gcs_client() -> storage.Client:
    return storage.Client(project="it", credentials=AnonymousCredentials(),
                          client_options={"api_endpoint": GCS_ENDPOINT})


@pytest.fixture
def bucket(gcs_client):
    name = f"it-{uuid.uuid4().hex[:12]}"
    try:
        created = gcs_client.create_bucket(name, timeout=5, retry=None)
    except Exception as exc:
        pytest.fail(f"GCS emulator not reachable at {GCS_ENDPOINT} ({exc}); {START_HINT}", pytrace=False)
    yield created
    for blob in gcs_client.list_blobs(name):
        blob.delete()
    created.delete()


@pytest.fixture
def gcs_storage(bucket, gcs_client) -> GCSStorage:
    return GCSStorage(bucket.name, client=gcs_client)


@pytest.fixture
def seed(db, bucket) -> Seed:
    return Seed(db, bucket)
