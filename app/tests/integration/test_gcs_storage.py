"""GCSStorage against the Cloud Storage emulator (same client library and API calls as production)."""
import pytest
from google.api_core.exceptions import NotFound

pytestmark = pytest.mark.integration


async def test_read_returns_object_bytes(gcs_storage, bucket):
    bucket.blob("cust-1/a.txt").upload_from_string(b"hello gcs")
    assert await gcs_storage.read("cust-1/a.txt") == b"hello gcs"


async def test_read_missing_object_raises_not_found(gcs_storage):
    with pytest.raises(NotFound):
        await gcs_storage.read("cust-1/missing.txt")


async def test_ping_sees_bucket(gcs_storage):
    assert await gcs_storage.ping() is True
