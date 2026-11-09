"""Object storage access. Google Cloud Storage in cloud, local filesystem for dev/tests.

Design choice: for anything larger than a small threshold the service does NOT proxy bytes.
It authorises the request and returns a short-lived V4 signed URL, so GCS serves the
download. That keeps pod CPU/network flat regardless of file size and makes the 300 ms
latency SLO about metadata + authorisation only.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path
from typing import Protocol


class StorageBackend(Protocol):
    async def read(self, object_key: str) -> bytes: ...
    async def signed_url(self, object_key: str, filename: str, ttl_seconds: int) -> str: ...
    async def ping(self) -> bool: ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, object_key: str) -> Path:
        p = (self._root / object_key).resolve()
        if self._root not in p.parents:          # defence in depth vs path traversal
            raise ValueError("object key escapes storage root")
        return p

    async def read(self, object_key: str) -> bytes:
        return await asyncio.to_thread(self._path(object_key).read_bytes)

    async def signed_url(self, object_key: str, filename: str, ttl_seconds: int) -> str:
        return f"http://localhost:8080/_local/{object_key}?ttl={ttl_seconds}"

    async def ping(self) -> bool:
        return self._root.exists()


class GCSStorage:
    """Uses Workload Identity (no key files). V4 signing goes through the IAM signBlob API,
    so signing credentials are the pod's own Google service account."""

    def __init__(self, bucket: str, client=None) -> None:  # client: google.cloud.storage.Client
        from google.auth.transport import requests as g_requests

        if client is None:  # production: Workload Identity via Application Default Credentials
            import google.auth
            from google.cloud import storage

            credentials, project = google.auth.default()
            client = storage.Client(project=project, credentials=credentials)
        # Injected client: integration tests point it at the GCS emulator.
        self._client = client
        self._credentials = client._credentials
        self._auth_request = g_requests.Request()
        self._bucket = client.bucket(bucket)

    async def read(self, object_key: str) -> bytes:
        return await asyncio.to_thread(self._bucket.blob(object_key).download_as_bytes, timeout=0.25)

    def _sign(self, object_key: str, filename: str, ttl_seconds: int) -> str:
        if not self._credentials.valid:
            self._credentials.refresh(self._auth_request)
        return self._bucket.blob(object_key).generate_signed_url(
            version="v4",
            expiration=dt.timedelta(seconds=ttl_seconds),
            method="GET",
            service_account_email=self._credentials.service_account_email,
            access_token=self._credentials.token,
            response_disposition=f'attachment; filename="{filename}"',
        )

    async def signed_url(self, object_key: str, filename: str, ttl_seconds: int) -> str:
        return await asyncio.to_thread(self._sign, object_key, filename, ttl_seconds)

    async def ping(self) -> bool:
        return await asyncio.to_thread(self._bucket.exists)
