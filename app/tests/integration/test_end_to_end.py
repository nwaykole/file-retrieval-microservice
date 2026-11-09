"""Whole request path with no fakes: HTTP -> session auth -> Postgres metadata -> GCS bytes."""
import httpx
import pytest

from file_service.config import Settings
from file_service.main import create_app
from file_service.repository import CachedRepository, PostgresRepository
from file_service.storage import GCSStorage

pytestmark = pytest.mark.integration

ALICE_PASSWORD = "alice-password-1"


@pytest.fixture
async def client(app_dsn, bucket, gcs_client):
    """The real app wired like production (cache in front of Postgres, GCS for bytes)."""
    repo = CachedRepository(await PostgresRepository.create(app_dsn, 1, 4), ttl=1, maxsize=100)
    storage = GCSStorage(bucket.name, client=gcs_client)
    # Generous timeout: these tests check behaviour; latency is checked by the k6 load test.
    settings = Settings(env="test", stream_max_bytes=1024, backend_timeout_seconds=2.0)
    app = create_app(repo=repo, storage=storage, settings=settings)
    async with app.router.lifespan_context(app):          # startup/shutdown, closes the pool
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


async def login(client, username="alice", password=ALICE_PASSWORD) -> httpx.Response:
    return await client.post("/auth/login", json={"username": username, "password": password})


async def test_login_list_download_logout(client, seed, db):
    await seed.user("alice", "cust-1", ALICE_PASSWORD)
    await seed.file("cust-1", "file-aaaa1111", b"hello world", filename="hello.txt")
    await seed.file("cust-1", "file-quar0001", b"infected", status="quarantined")

    assert (await client.get("/v1/files")).status_code == 401
    assert (await login(client, password="wrong-password-1")).status_code == 401
    assert (await login(client)).status_code == 200
    assert await db.fetchval("SELECT count(*) FROM sessions") == 1

    listing = await client.get("/v1/files")
    assert listing.status_code == 200
    assert [f["file_id"] for f in listing.json()] == ["file-aaaa1111"]

    download = await client.get("/v1/files/file-aaaa1111/content")
    assert download.status_code == 200
    assert download.content == b"hello world"
    assert 'filename="hello.txt"' in download.headers["content-disposition"]
    assert (await client.get("/v1/files/file-quar0001/content")).status_code == 404

    token = client.cookies.get("fs_session")
    assert (await client.post("/auth/logout")).status_code == 204
    assert await db.fetchval("SELECT count(*) FROM sessions") == 0
    # The old cookie is useless after logout: the session is gone server-side.
    replay = await client.get("/v1/files", headers={"Cookie": f"fs_session={token}"})
    assert replay.status_code == 401


async def test_customer_cannot_reach_another_customers_file(client, seed):
    await seed.user("alice", "cust-1", ALICE_PASSWORD)
    await seed.user("bob", "cust-2", "bob-password-123")
    await seed.file("cust-2", "file-bbbb2222", b"bob's secret")

    assert (await login(client)).status_code == 200
    assert (await client.get("/v1/files/file-bbbb2222")).status_code == 404
    assert (await client.get("/v1/files/file-bbbb2222/content")).status_code == 404
    assert (await client.get("/v1/files")).json() == []


async def test_expired_session_is_rejected(client, seed, db):
    await seed.user("alice", "cust-1", ALICE_PASSWORD)
    assert (await login(client)).status_code == 200

    await db.execute("UPDATE sessions SET expires_at = now() - interval '1 second'")
    assert (await client.get("/v1/files")).status_code == 401


async def test_missing_object_in_bucket_is_503_not_500(client, seed):
    await seed.user("alice", "cust-1", ALICE_PASSWORD)
    await seed.file("cust-1", "file-gone0001", size_bytes=10)     # metadata row, no object
    assert (await login(client)).status_code == 200

    response = await client.get("/v1/files/file-gone0001/content")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"


async def test_readiness_checks_the_real_database(client):
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
