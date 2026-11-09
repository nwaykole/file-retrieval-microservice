"""File metadata lookup. Postgres in cloud, in-memory for local runs and tests.

A small in-process TTL cache sits in front of the database: metadata is read-heavy and
rarely changes, so this removes most DB round trips from the hot path at 6k req/s.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from cachetools import TTLCache


@dataclass(frozen=True)
class FileRecord:
    file_id: str
    customer_id: str
    object_key: str
    filename: str
    content_type: str
    size_bytes: int
    status: str = "available"   # available | quarantined | deleted


class MetadataRepository(Protocol):
    async def get(self, customer_id: str, file_id: str) -> FileRecord | None: ...
    async def list_for_customer(self, customer_id: str, limit: int) -> list[FileRecord]: ...
    async def ping(self) -> bool: ...


@dataclass(frozen=True)
class UserRecord:
    username: str
    customer_id: str
    password_hash: str


@dataclass(frozen=True)
class SessionRecord:
    username: str
    customer_id: str


class InMemoryRepository:
    def __init__(self, records: list[FileRecord] | None = None) -> None:
        self._records = {(r.customer_id, r.file_id): r for r in records or []}
        self._users: dict[str, UserRecord] = {}
        self._sessions: dict[str, tuple[SessionRecord, datetime]] = {}

    def add(self, record: FileRecord) -> None:
        self._records[(record.customer_id, record.file_id)] = record

    async def get(self, customer_id: str, file_id: str) -> FileRecord | None:
        return self._records.get((customer_id, file_id))

    async def list_for_customer(self, customer_id: str, limit: int) -> list[FileRecord]:
        return [r for (c, _), r in self._records.items() if c == customer_id][:limit]

    async def ping(self) -> bool:
        return True

    def add_user(self, username: str, customer_id: str, password_hash: str) -> None:
        self._users[username] = UserRecord(username, customer_id, password_hash)

    async def get_user(self, username: str) -> UserRecord | None:
        return self._users.get(username)

    async def create_session(self, token_hash: str, username: str, expires_at: datetime) -> None:
        user = self._users.get(username)
        if user is not None:
            self._sessions[token_hash] = (SessionRecord(user.username, user.customer_id), expires_at)

    async def get_session(self, token_hash: str) -> SessionRecord | None:
        session = self._sessions.get(token_hash)
        if session is None:
            return None
        if session[1] <= datetime.now(UTC):
            self._sessions.pop(token_hash, None)
            return None
        return session[0]

    async def delete_session(self, token_hash: str) -> None:
        self._sessions.pop(token_hash, None)


class PostgresRepository:
    """Every query is scoped by customer_id: tenant isolation is enforced in the query itself."""

    def __init__(self, pool) -> None:  # asyncpg.Pool
        self._pool = pool

    @classmethod
    async def create(cls, dsn: str, min_size: int, max_size: int) -> PostgresRepository:
        import asyncpg
        return cls(await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size,
                                             ssl=False, command_timeout=0.2))

    async def get(self, customer_id: str, file_id: str) -> FileRecord | None:
        row = await self._pool.fetchrow(
            "SELECT file_id, customer_id, object_key, filename, content_type, size_bytes, status "
            "FROM files WHERE customer_id = $1 AND file_id = $2", customer_id, file_id)
        return FileRecord(**dict(row)) if row else None

    async def list_for_customer(self, customer_id: str, limit: int) -> list[FileRecord]:
        rows = await self._pool.fetch(
            "SELECT file_id, customer_id, object_key, filename, content_type, size_bytes, status "
            "FROM files WHERE customer_id = $1 AND status = 'available' "
            "ORDER BY created_at DESC LIMIT $2", customer_id, limit)
        return [FileRecord(**dict(r)) for r in rows]

    async def ping(self) -> bool:
        return await self._pool.fetchval("SELECT 1") == 1

    async def get_user(self, username: str) -> UserRecord | None:
        row = await self._pool.fetchrow(
            "SELECT username, customer_id, password_hash FROM users WHERE username = $1", username)
        return UserRecord(**dict(row)) if row else None

    async def create_session(self, token_hash: str, username: str, expires_at: datetime) -> None:
        await self._pool.execute(
            "INSERT INTO sessions (token_hash, username, expires_at) VALUES ($1, $2, $3)",
            token_hash, username, expires_at)
        await self._pool.execute("DELETE FROM sessions WHERE expires_at <= now()")

    async def get_session(self, token_hash: str) -> SessionRecord | None:
        row = await self._pool.fetchrow(
            "SELECT u.username, u.customer_id FROM sessions s "
            "JOIN users u ON u.username = s.username "
            "WHERE s.token_hash = $1 AND s.expires_at > now()", token_hash)
        return SessionRecord(**dict(row)) if row else None

    async def delete_session(self, token_hash: str) -> None:
        await self._pool.execute("DELETE FROM sessions WHERE token_hash = $1", token_hash)

    async def close(self) -> None:
        await self._pool.close()


class CachedRepository:
    """Read-through TTL cache. Negative results are not cached (new uploads appear quickly)."""

    def __init__(self, inner: MetadataRepository, ttl: int, maxsize: int) -> None:
        self._inner = inner
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = asyncio.Lock()

    async def get(self, customer_id: str, file_id: str) -> FileRecord | None:
        key = (customer_id, file_id)
        if (hit := self._cache.get(key)) is not None:
            return hit
        record = await self._inner.get(customer_id, file_id)
        if record is not None:
            async with self._lock:
                self._cache[key] = record
        return record

    async def list_for_customer(self, customer_id: str, limit: int) -> list[FileRecord]:
        return await self._inner.list_for_customer(customer_id, limit)

    async def ping(self) -> bool:
        return await self._inner.ping()
