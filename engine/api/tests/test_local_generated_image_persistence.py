import asyncio
from pathlib import Path

from api.v1.auth.context import reset_current_owner_id, set_current_owner_id
from utils.oss_storage import persist_generated_image


def test_local_generated_image_is_copied_to_owner_scoped_app_data(
    tmp_path, monkeypatch
):
    app_data = tmp_path / "app-data"
    source = tmp_path / "provider-output.png"
    source.write_bytes(b"png-bytes")
    owner = "d8d62efc-2ad0-420d-b837-7cf82e9cec5d"
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(app_data))
    monkeypatch.setenv("ALIYUN_OSS_ENABLED", "false")
    token = set_current_owner_id(owner)
    try:
        stored = asyncio.run(persist_generated_image(str(source)))
    finally:
        reset_current_owner_id(token)

    stored_path = Path(stored)
    assert stored_path.is_file()
    assert stored_path.read_bytes() == b"png-bytes"
    assert stored_path.parent == app_data / "images" / "users" / owner
    assert source.is_file()
