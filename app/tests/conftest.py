import pytest
from fastapi.testclient import TestClient

from file_service.auth import hash_password
from file_service.config import Settings
from file_service.main import create_app
from file_service.repository import FileRecord, InMemoryRepository
from file_service.storage import LocalStorage


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(env="test", storage_backend="local",
                    local_storage_root=str(tmp_path / "files"), stream_max_bytes=1024,
                    metadata_cache_ttl_seconds=1)


@pytest.fixture
def repo() -> InMemoryRepository:
    result = InMemoryRepository([
        FileRecord("file-aaaa1111", "cust-1", "cust-1/small.txt", "small.txt", "text/plain", 11),
        FileRecord("file-bbbb2222", "cust-1", "cust-1/big.bin", "big.bin", "application/octet-stream", 50_000),
        FileRecord("file-cccc3333", "cust-2", "cust-2/secret.txt", "secret.txt", "text/plain", 6),
        FileRecord("file-dddd4444", "cust-1", "cust-1/virus.exe", "virus.exe", "application/octet-stream", 10,
                   status="quarantined"),
    ])
    result.add_user("user-1", "cust-1", hash_password("test-password-1"))
    result.add_user("user-2", "cust-2", hash_password("test-password-2"))
    return result


@pytest.fixture
def storage(settings) -> LocalStorage:
    s = LocalStorage(settings.local_storage_root)
    (s._root / "cust-1").mkdir()
    (s._root / "cust-1" / "small.txt").write_bytes(b"hello world")
    return s


@pytest.fixture
def client(settings, repo, storage):
    with TestClient(create_app(repo=repo, storage=storage, settings=settings), follow_redirects=False) as c:
        yield c


@pytest.fixture
def auth(client):
    def _auth(target=None, username="user-1"):
        target = target or client
        password = "test-password-1" if username == "user-1" else "test-password-2"
        response = target.post("/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200
        assert response.cookies.get("fs_session")
        return {}
    return _auth
