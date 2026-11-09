"""API behaviour: authentication, tenant isolation, downloads, probes and resilience."""
import asyncio

import pytest

from file_service.main import content_disposition
from file_service.repository import CachedRepository, FileRecord, InMemoryRepository


def test_missing_session_is_401(client):
    assert client.get("/v1/files/file-aaaa1111").status_code == 401


def test_invalid_credentials_are_401(client):
    response = client.post("/auth/login", json={"username": "user-1", "password": "wrong-password"})
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid username or password"


def test_unknown_user_has_same_login_error(client):
    response = client.post("/auth/login", json={"username": "unknown", "password": "wrong-password"})
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid username or password"


def test_login_sets_http_only_cookie(client):
    response = client.post("/auth/login", json={"username": "user-1", "password": "test-password-1"})
    cookie = response.headers["set-cookie"].lower()
    assert response.status_code == 200
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_logout_revokes_session(client, auth):
    auth()
    assert client.get("/v1/files").status_code == 200
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/v1/files").status_code == 401


# ---------- tenant isolation ----------
def test_cannot_read_other_customers_file(client, auth):
    auth()
    assert client.get("/v1/files/file-cccc3333").status_code == 404


def test_list_only_returns_own_files(client, auth):
    auth(username="user-2")
    response = client.get("/v1/files")
    assert response.status_code == 200
    assert [f["file_id"] for f in response.json()] == ["file-cccc3333"]


def test_quarantined_file_not_served(client, auth):
    auth()
    assert client.get("/v1/files/file-dddd4444/content").status_code == 404


# ---------- input validation ----------
@pytest.mark.parametrize("bad_id", ["..%2F..%2Fetc%2Fpasswd", "a", "x" * 65, "abc$def12", "id%00null"])
def test_bad_file_ids_rejected(client, auth, bad_id):
    auth()
    assert client.get(f"/v1/files/{bad_id}").status_code in (404, 422)


def test_list_limit_bounds(client, auth):
    auth()
    assert client.get("/v1/files?limit=0").status_code == 422
    assert client.get("/v1/files?limit=10000").status_code == 422


def test_content_disposition_blocks_header_injection():
    header = content_disposition('evil"\r\nSet-Cookie: x=1.txt')
    assert "\r" not in header and "\n" not in header
    assert header.startswith('attachment; filename="evilSet-Cookie: x=1.txt"')


# ---------- happy paths ----------
def test_metadata(client, auth):
    auth()
    response = client.get("/v1/files/file-aaaa1111")
    assert response.status_code == 200
    assert response.json() == {"file_id": "file-aaaa1111", "filename": "small.txt",
                               "content_type": "text/plain", "size_bytes": 11}
    assert "x-request-id" in response.headers
    assert response.headers["cache-control"] == "no-store"


def test_small_file_streamed(client, auth):
    auth()
    response = client.get("/v1/files/file-aaaa1111/content")
    assert response.status_code == 200
    assert response.content == b"hello world"
    assert "attachment" in response.headers["content-disposition"]


def test_large_file_redirects_to_signed_url(client, auth):
    auth()
    response = client.get("/v1/files/file-bbbb2222/content")
    assert response.status_code == 302
    assert "cust-1/big.bin" in response.headers["location"]


def test_request_id_propagated(client, auth):
    auth()
    response = client.get("/v1/files/file-aaaa1111", headers={"x-request-id": "abc123"})
    assert response.headers["x-request-id"] == "abc123"


# ---------- resilience ----------
class SlowRepo(InMemoryRepository):
    async def get(self, customer_id, file_id):
        await asyncio.sleep(1)


class BrokenRepo(InMemoryRepository):
    async def get(self, customer_id, file_id):
        raise ConnectionError("db down")

    async def ping(self):
        return False


def _client_with(repo, settings, storage):
    from fastapi.testclient import TestClient

    from file_service.main import create_app
    return TestClient(create_app(repo=repo, storage=storage, settings=settings))


def test_slow_backend_fails_fast_with_503(settings, storage):
    from file_service.auth import hash_password

    repo = SlowRepo()
    repo.add_user("user-1", "cust-1", hash_password("test-password-1"))
    with _client_with(repo, settings, storage) as client:
        client.post("/auth/login", json={"username": "user-1", "password": "test-password-1"})
        response = client.get("/v1/files/file-aaaa1111")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"


def test_backend_error_is_503_not_500(settings, storage):
    with _client_with(BrokenRepo(), settings, storage) as client:
        response = client.get("/readyz")
        assert response.status_code == 503


async def test_cache_serves_repeat_reads():
    calls = 0

    class Counting(InMemoryRepository):
        async def get(self, customer_id, file_id):
            nonlocal calls
            calls += 1
            return await super().get(customer_id, file_id)

    inner = Counting([FileRecord("f1234567", "c", "k", "n", "t", 1)])
    cached = CachedRepository(inner, ttl=60, maxsize=10)
    for _ in range(5):
        assert await cached.get("c", "f1234567") is not None
    assert calls == 1


# ---------- homepage ----------
def test_homepage_is_public_welcome_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Welcome to nginx!" in response.text


# ---------- probes / metrics ----------
def test_probes_and_metrics(client, auth):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").json() == {"status": "ready"}
    auth()
    client.get("/v1/files/file-aaaa1111")
    metrics = client.get("/metrics").text
    assert 'http_requests_total{method="GET",route="/v1/files/{file_id}",status="200"}' in metrics
    assert "http_request_duration_seconds_bucket" in metrics
