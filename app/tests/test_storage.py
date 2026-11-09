import pytest

from file_service.storage import LocalStorage


async def test_local_storage_blocks_path_traversal(tmp_path):
    s = LocalStorage(str(tmp_path / "root"))
    (tmp_path / "outside.txt").write_text("secret")
    with pytest.raises(ValueError):
        await s.read("../outside.txt")


async def test_local_storage_reads(tmp_path):
    s = LocalStorage(str(tmp_path))
    (tmp_path / "a.txt").write_bytes(b"x")
    assert await s.read("a.txt") == b"x"
