"""PostgresRepository against real Postgres, connected as the least-privilege app role."""
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from file_service.auth import hash_session_token

pytestmark = pytest.mark.integration

IN_ONE_HOUR = timedelta(hours=1)


async def test_ping(repo):
    assert await repo.ping() is True


# ---------- file metadata ----------
async def test_get_is_scoped_to_customer(repo, seed):
    await seed.file("cust-1", "file-aaaa1111", b"hello")

    record = await repo.get("cust-1", "file-aaaa1111")
    assert record is not None
    assert (record.object_key, record.size_bytes, record.status) == ("cust-1/file-aaaa1111", 5, "available")
    assert await repo.get("cust-2", "file-aaaa1111") is None   # same id, wrong tenant


async def test_list_is_own_available_files_newest_first(repo, seed):
    await seed.file("cust-1", "file-old00001", age_seconds=300)
    await seed.file("cust-1", "file-new00001")
    await seed.file("cust-1", "file-quar0001", status="quarantined")
    await seed.file("cust-2", "file-other001")

    records = await repo.list_for_customer("cust-1", limit=50)
    assert [r.file_id for r in records] == ["file-new00001", "file-old00001"]
    assert [r.file_id for r in await repo.list_for_customer("cust-1", limit=1)] == ["file-new00001"]


async def test_schema_rejects_unknown_status(db):
    with pytest.raises(asyncpg.CheckViolationError):
        await db.execute("INSERT INTO files (customer_id, file_id, object_key, filename, content_type, size_bytes, "
                         "status) VALUES ('c', 'f', 'k', 'n', 't', 1, 'bogus')")


# ---------- accounts and sessions ----------
async def test_get_user(repo, seed):
    await seed.user("alice", "cust-1", "alice-password-1")

    user = await repo.get_user("alice")
    assert user is not None
    assert user.customer_id == "cust-1"
    assert user.password_hash.startswith("scrypt$")      # never stored in plain text
    assert await repo.get_user("nobody") is None


async def test_session_lifecycle(repo, seed):
    await seed.user("alice", "cust-1", "alice-password-1")
    token_hash = hash_session_token("token-1")

    await repo.create_session(token_hash, "alice", datetime.now(UTC) + IN_ONE_HOUR)
    session = await repo.get_session(token_hash)
    assert session is not None
    assert (session.username, session.customer_id) == ("alice", "cust-1")

    await repo.delete_session(token_hash)
    assert await repo.get_session(token_hash) is None


async def test_expired_session_is_rejected_and_purged(repo, seed, db):
    await seed.user("alice", "cust-1", "alice-password-1")
    expired = hash_session_token("old-token")
    await db.execute("INSERT INTO sessions (token_hash, username, expires_at) VALUES ($1, 'alice', $2)",
                     expired, datetime.now(UTC) - timedelta(seconds=1))

    assert await repo.get_session(expired) is None
    # Creating any new session purges expired rows.
    await repo.create_session(hash_session_token("new-token"), "alice", datetime.now(UTC) + IN_ONE_HOUR)
    assert await db.fetchval("SELECT count(*) FROM sessions WHERE token_hash = $1", expired) == 0


async def test_deleting_user_revokes_their_sessions(repo, seed, db):
    await seed.user("alice", "cust-1", "alice-password-1")
    token_hash = hash_session_token("token-1")
    await repo.create_session(token_hash, "alice", datetime.now(UTC) + IN_ONE_HOUR)

    await db.execute("DELETE FROM users WHERE username = 'alice'")
    assert await repo.get_session(token_hash) is None


# ---------- least privilege: the grants in schema.sql ----------
@pytest.mark.parametrize("statement", [
    "INSERT INTO files (customer_id, file_id, object_key, filename, content_type, size_bytes) "
    "VALUES ('c', 'f', 'k', 'n', 't', 1)",
    "UPDATE files SET status = 'available'",
    "DELETE FROM files",
    "INSERT INTO users (username, customer_id, password_hash) VALUES ('mallory', 'c', 'x')",
    "UPDATE users SET customer_id = 'someone-else'",
    "DROP TABLE sessions",
])
async def test_app_role_cannot_modify_files_or_accounts(app_conn, statement):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute(statement)
