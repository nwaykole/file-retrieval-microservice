"""Customer file retrieval service.

Request path (hot path, target p99.9 < 300 ms):
  authenticate session -> validate input -> metadata lookup (cached, tenant-scoped)
  -> small file: stream bytes | large file: 302 to short-lived signed URL
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from .auth import (Principal, dummy_password_hash, hash_password, hash_session_token,
                   new_session_token, verify_password)
from .config import Settings, get_settings
from .observability import BACKEND_ERRORS, RequestContextMiddleware, configure_logging, configure_tracing
from .repository import CachedRepository, FileRecord, InMemoryRepository, MetadataRepository, PostgresRepository
from .storage import GCSStorage, LocalStorage, StorageBackend
from .ui import router as ui_router

log = logging.getLogger("file_service")

# ULID / UUID-ish ids only: rejects traversal, wildcards and injection payloads at the edge.
FileId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{8,64}$")]

# Static homepage, same as the Stage 2 nginx placeholder, so "/" keeps working after the
# switch to the real service. Contains no user input.
WELCOME_PAGE = """<!DOCTYPE html>
<html>
<head>
<title>Welcome to nginx!</title>
<style>
html { color-scheme: light dark; }
body { width: 35em; margin: 0 auto;
font-family: Tahoma, Verdana, Arial, sans-serif; }
</style>
</head>
<body>
<h1>Welcome to nginx!</h1>
<p>If you see this page, the nginx web server is successfully installed and
working. Further configuration is required.</p>

<p>For online documentation and support please refer to
<a href="http://nginx.org/">nginx.org</a>.<br/>
Commercial support is available at
<a href="http://nginx.com/">nginx.com</a>.</p>

<p><em>Thank you for using nginx.</em></p>
</body>
</html>
"""


def content_disposition(filename: str) -> str:
    """Prevent header injection: keep a safe ASCII fallback and an RFC 5987 UTF-8 form."""
    from urllib.parse import quote
    safe = "".join(c for c in filename if c.isprintable() and c not in '"\\\r\n;')[:200] or "download"
    ascii_name = safe.encode("ascii", "replace").decode()
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename[:200])}'


class FileMetadata(BaseModel):
    file_id: str
    filename: str
    content_type: str
    size_bytes: int

    @classmethod
    def of(cls, r: FileRecord) -> FileMetadata:
        return cls(file_id=r.file_id, filename=r.filename, content_type=r.content_type,
                   size_bytes=r.size_bytes)


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._@+-]*$")
    password: str = Field(min_length=12, max_length=1024)


async def build_backends(s: Settings) -> tuple[MetadataRepository, StorageBackend]:
    if s.metadata_backend == "postgres":
        if not s.database_url:
            raise RuntimeError("FS_DATABASE_URL required for postgres backend")
        inner: MetadataRepository = await PostgresRepository.create(s.database_url, s.db_pool_min, s.db_pool_max)
    else:
        inner = InMemoryRepository()
        if s.local_username and s.local_password and s.local_customer_id:
            inner.add_user(s.local_username.strip().lower(), s.local_customer_id, hash_password(s.local_password))
    repo = CachedRepository(inner, ttl=s.metadata_cache_ttl_seconds, maxsize=s.metadata_cache_size)
    storage: StorageBackend = (GCSStorage(s.storage_bucket) if s.storage_backend == "gcs"
                               else LocalStorage(s.local_storage_root))
    return repo, storage


def create_app(repo: MetadataRepository | None = None, storage: StorageBackend | None = None,
               settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if repo is None or storage is None:
            app.state.repo, app.state.storage = await build_backends(settings)
        else:
            app.state.repo, app.state.storage = repo, storage
        app.state.auth_store = getattr(app.state.repo, "_inner", app.state.repo)
        app.state.ready = True
        log.info("startup complete", extra={"extra_fields": {"env": settings.env}})
        yield
        app.state.ready = False          # fail readiness first so the LB drains us
        inner = getattr(app.state.repo, "_inner", None)
        if hasattr(inner, "close"):
            await inner.close()

    app = FastAPI(title="file-service", version="1.0.0", lifespan=lifespan,
                  docs_url=None if settings.env == "prod" else "/docs", redoc_url=None)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(ui_router)          # browser login page at /login
    app.dependency_overrides[get_settings] = lambda: settings
    configure_tracing(app)

    async def with_timeout(coro, backend: str):
        try:
            return await asyncio.wait_for(coro, timeout=settings.backend_timeout_seconds)
        except TimeoutError:
            BACKEND_ERRORS.labels(backend, "timeout").inc()
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "upstream timeout",
                                headers={"Retry-After": "1"}) from None
        except HTTPException:
            raise
        except Exception:
            BACKEND_ERRORS.labels(backend, "error").inc()
            log.exception("backend failure", extra={"extra_fields": {"backend": backend}})
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "upstream unavailable",
                                headers={"Retry-After": "1"}) from None

    async def require_principal(request: Request) -> Principal:
        token = request.cookies.get(settings.session_cookie_name)
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing session")
        session = await with_timeout(
            request.app.state.auth_store.get_session(hash_session_token(token)), "auth")
        if session is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing session")
        return Principal(customer_id=session.customer_id, subject=session.username)

    async def load_record(request: Request, principal: Principal, file_id: str) -> FileRecord:
        record = await with_timeout(request.app.state.repo.get(principal.customer_id, file_id), "metadata")
        # 404 (not 403) for other tenants' files: don't leak existence.
        if record is None or record.status != "available":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
        return record

    # ---------------- homepage ----------------
    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    async def homepage():
        return WELCOME_PAGE

    # ---------------- probes & metrics ----------------
    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz(request: Request):
        # Readiness checks only cheap local state + metadata store. A storage blip should not
        # take every pod out of the LB at once (that turns a partial outage into a total one).
        if not getattr(request.app.state, "ready", False):
            return JSONResponse({"status": "starting"}, status_code=503)
        try:
            ok = await asyncio.wait_for(request.app.state.repo.ping(), timeout=0.5)
        except Exception:
            ok = False
        return JSONResponse({"status": "ready" if ok else "degraded"}, status_code=200 if ok else 503)

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/auth/login")
    async def login(credentials: LoginRequest, request: Request, response: Response):
        username = credentials.username.strip().lower()
        user = await with_timeout(request.app.state.auth_store.get_user(username), "auth")
        encoded_hash = user.password_hash if user else dummy_password_hash()
        valid = await asyncio.to_thread(verify_password, credentials.password, encoded_hash)
        if user is None or not valid:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")

        token = new_session_token()
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.session_ttl_seconds)
        await with_timeout(
            request.app.state.auth_store.create_session(hash_session_token(token), username, expires_at),
            "auth")
        response.set_cookie(
            key=settings.session_cookie_name,
            value=token,
            max_age=settings.session_ttl_seconds,
            httponly=True,
            secure=settings.env not in {"local", "test"},
            samesite="lax",
            path="/",
        )
        return {"status": "ok"}

    @app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(request: Request, response: Response):
        token = request.cookies.get(settings.session_cookie_name)
        if token:
            await with_timeout(
                request.app.state.auth_store.delete_session(hash_session_token(token)), "auth")
        response.delete_cookie(
            key=settings.session_cookie_name,
            httponly=True,
            secure=settings.env not in {"local", "test"},
            samesite="lax",
            path="/",
        )

    # ---------------- API ----------------
    @app.get("/v1/files", response_model=list[FileMetadata])
    async def list_files(request: Request, principal: Principal = Depends(require_principal),
                         limit: int = Query(50, ge=1, le=200)):
        records = await with_timeout(request.app.state.repo.list_for_customer(principal.customer_id, limit), "metadata")
        return [FileMetadata.of(r) for r in records]

    @app.get("/v1/files/{file_id}", response_model=FileMetadata)
    async def get_metadata(file_id: FileId, request: Request, principal: Principal = Depends(require_principal)):
        return FileMetadata.of(await load_record(request, principal, file_id))

    @app.get("/v1/files/{file_id}/content")
    async def download(file_id: FileId, request: Request, principal: Principal = Depends(require_principal)):
        record = await load_record(request, principal, file_id)
        storage: StorageBackend = request.app.state.storage
        log.info("file access", extra={"extra_fields": {
            "audit": True, "customer_id": principal.customer_id, "subject": principal.subject,
            "file_id": file_id}})
        if record.size_bytes <= settings.stream_max_bytes:
            data = await with_timeout(storage.read(record.object_key), "storage")
            return Response(data, media_type=record.content_type, headers={
                "content-disposition": content_disposition(record.filename)})
        url = await with_timeout(storage.signed_url(record.object_key, record.filename,
                                                     settings.signed_url_ttl_seconds), "storage")
        return RedirectResponse(url, status_code=status.HTTP_302_FOUND)

    return app
