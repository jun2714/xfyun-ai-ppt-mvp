"""Aliyun OSS for PPT originals, slide images, and exports.

Local disk is only a scratch pad while parsing/rendering. Permanent files go
to object storage so the Baota server does not fill up across kindergartens.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
from typing import Optional
from urllib.parse import quote, unquote, urlparse

from utils.get_env import (
    get_aliyun_oss_access_key_id,
    get_aliyun_oss_access_key_secret,
    get_aliyun_oss_bucket,
    get_aliyun_oss_endpoint,
    get_aliyun_oss_key_prefix,
    get_aliyun_oss_public_base_url,
    is_aliyun_oss_enabled,
)

LOGGER = logging.getLogger(__name__)

PPTX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


def is_oss_enabled() -> bool:
    return is_aliyun_oss_enabled()


def is_local_app_data_url(value: str | None) -> bool:
    """True for FastAPI-served /app_data files, including the /ppt-api reverse proxy."""
    text = (value or "").strip()
    if not text:
        return False
    path = unquote(urlparse(text).path or "") if text.startswith(("http://", "https://")) else text
    if not path.startswith("/"):
        path = "/" + path.lstrip("/")
    return path.startswith("/ppt-api/app_data/") or path.startswith("/app_data/")


def is_oss_url(value: str | None) -> bool:
    if not value:
        return False
    text = value.strip()
    if not text.startswith(("http://", "https://")):
        return False
    if is_local_app_data_url(text):
        return False
    public_base = get_aliyun_oss_public_base_url()
    if public_base and text.startswith(public_base + "/"):
        return True
    host = (urlparse(text).hostname or "").lower()
    if "aliyuncs.com" in host:
        return True
    if public_base:
        public_host = (urlparse(public_base).hostname or "").lower()
        return bool(public_host) and host == public_host
    return False


def public_url_for_key(key: str) -> str:
    encoded = "/".join(
        quote(part, safe="-_.~") for part in key.lstrip("/").split("/") if part
    )
    return f"{get_aliyun_oss_public_base_url()}/{encoded}"


def sign_get_url(url: str, expires: int = 86400 * 7) -> str:
    """Sign a private OSS object so the browser can download or show it."""
    text = (url or "").strip()
    if not text or not is_oss_enabled() or not is_oss_url(text):
        return text
    key = object_key_from_url(text)
    if not key:
        return text
    try:
        bucket = _bucket()
        try:
            return bucket.sign_url("GET", key, expires, slash_safe=True)
        except TypeError:
            return bucket.sign_url("GET", key, expires)
    except Exception:
        LOGGER.warning("[oss] sign_url failed key=%s", key, exc_info=True)
        return text


def object_key_from_url(url: str) -> Optional[str]:
    text = (url or "").strip()
    if not text:
        return None
    public_base = get_aliyun_oss_public_base_url()
    if public_base and text.startswith(public_base + "/"):
        return unquote(text[len(public_base) + 1 :].split("?", 1)[0])
    parsed = urlparse(text)
    path = unquote((parsed.path or "").lstrip("/"))
    bucket = get_aliyun_oss_bucket()
    if bucket and path.startswith(f"{bucket}/"):
        path = path[len(bucket) + 1 :]
    prefix = get_aliyun_oss_key_prefix()
    if prefix and not path.startswith(f"{prefix}/"):
        return None
    return path or None


# OSS 前缀即文件夹。第一次上传该路径时控制台会自动出现对应目录，无需预先创建。
OSS_AREA_LIBRARY = "library"
OSS_AREA_TEMPLATES = "templates"
OSS_AREA_IMAGES = "images"
OSS_AREA_EXPORTS = "exports"


def safe_folder_name(name: str, fallback: str = "其他") -> str:
    text = (name or "").strip().replace("\\", "/").replace("..", "")
    text = "/".join(part for part in text.split("/") if part not in {"", ".", ".."})
    text = text.replace("/", "-")
    return text or fallback


def build_object_key(*parts: str) -> str:
    prefix = get_aliyun_oss_key_prefix()
    cleaned = [prefix] if prefix else []
    for part in parts:
        piece = str(part).replace("\\", "/").strip("/")
        if piece:
            cleaned.append(piece)
    return "/".join(cleaned)


def library_object_key(category: str, item_id: str, filename: str) -> str:
    return build_object_key(
        OSS_AREA_LIBRARY,
        safe_folder_name(category),
        str(item_id),
        filename,
    )


def _content_type_for(key: str, content_type: str | None) -> str:
    if content_type:
        return content_type
    guessed, _ = mimetypes.guess_type(key)
    if guessed:
        return guessed
    if key.lower().endswith(".pptx"):
        return PPTX_CONTENT_TYPE
    return "application/octet-stream"


def _ascii_download_name(download_name: str) -> str:
    """HTTP headers must be latin-1; keep an ASCII fallback for filename=."""
    leaf = (download_name or "").replace("\\", "/").split("/")[-1]
    ascii_chars: list[str] = []
    for ch in leaf:
        if ch.isascii() and (ch.isalnum() or ch in "._-"):
            ascii_chars.append(ch)
        elif ch in " \t":
            ascii_chars.append("_")
    text = "".join(ascii_chars).strip("._")
    if "." not in text:
        ext = ""
        if "." in leaf:
            ext = "." + "".join(
                c for c in leaf.rsplit(".", 1)[-1] if c.isascii() and c.isalnum()
            )
        text = f"file{ext or '.bin'}"
    return text[:180]


def _put_headers(
    *,
    content_type: str,
    download_name: str | None,
) -> dict[str, str]:
    headers = {
        "Content-Type": content_type,
        "x-oss-object-acl": "public-read",
    }
    if download_name:
        encoded = quote(download_name, safe="")
        ascii_name = _ascii_download_name(download_name)
        headers["Content-Disposition"] = (
            f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"
        )
    else:
        headers["Content-Disposition"] = "inline"
    return headers


def _bucket():
    import oss2

    endpoint = get_aliyun_oss_endpoint()
    if endpoint and "://" not in endpoint:
        endpoint = f"https://{endpoint}"
    auth = oss2.Auth(
        get_aliyun_oss_access_key_id(),
        get_aliyun_oss_access_key_secret(),
    )
    return oss2.Bucket(auth, endpoint, get_aliyun_oss_bucket())


def _put_object_sync(
    key: str,
    data: bytes,
    *,
    content_type: str | None,
    download_name: str | None,
) -> str:
    bucket = _bucket()
    headers = _put_headers(
        content_type=_content_type_for(key, content_type),
        download_name=download_name,
    )
    try:
        result = bucket.put_object(key, data, headers=headers)
    except Exception as exc:
        # Newer buckets may disable object ACL and rely on bucket policy.
        if "x-oss-object-acl" in headers:
            headers.pop("x-oss-object-acl", None)
            LOGGER.warning("[oss] retry put_object without object ACL key=%s err=%s", key, exc)
            result = bucket.put_object(key, data, headers=headers)
        else:
            raise
    if getattr(result, "status", 200) not in (200, 201):
        raise RuntimeError(f"OSS put_object failed status={getattr(result, 'status', None)}")
    return public_url_for_key(key)


def _delete_object_sync(key: str) -> None:
    bucket = _bucket()
    bucket.delete_object(key)


def _get_object_to_file_sync(key: str, dest: str) -> None:
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    bucket = _bucket()
    bucket.get_object_to_file(key, dest)


async def materialize_url_to_file(url: str, dest: str) -> str:
    """Copy an OSS or local library object onto disk for re-preview."""
    text = (url or "").strip()
    if not text:
        raise FileNotFoundError("empty asset url")
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    from utils.asset_directory_utils import resolve_app_path_to_filesystem

    local_path = resolve_app_path_to_filesystem(text)
    if local_path and os.path.isfile(local_path):
        if os.path.abspath(local_path) != os.path.abspath(dest):
            import shutil

            shutil.copy2(local_path, dest)
        return dest
    if os.path.isfile(text):
        if os.path.abspath(text) != os.path.abspath(dest):
            import shutil

            shutil.copy2(text, dest)
        return dest
    if is_oss_url(text):
        key = object_key_from_url(text)
        if not key:
            raise FileNotFoundError(text)
        await asyncio.to_thread(_get_object_to_file_sync, key, dest)
        return dest
    raise FileNotFoundError(text)


async def persist_bytes(
    data: bytes,
    key: str,
    *,
    content_type: str | None = None,
    download_name: str | None = None,
) -> str:
    if not is_oss_enabled():
        raise RuntimeError("阿里云 OSS 未配置")
    if not data:
        raise ValueError("empty object")
    return await asyncio.to_thread(
        _put_object_sync,
        key,
        data,
        content_type=content_type,
        download_name=download_name,
    )


async def persist_local_path(
    file_path: str,
    key: str,
    *,
    content_type: str | None = None,
    download_name: str | None = None,
    delete_local: bool = False,
    **kwargs,
) -> str:
    with open(file_path, "rb") as handle:
        data = handle.read()
    url = await persist_bytes(
        data,
        key,
        content_type=content_type,
        download_name=download_name,
    )
    if delete_local or kwargs.get("delete_local"):
        try:
            os.remove(file_path)
        except OSError:
            LOGGER.warning("[oss] failed to delete local file path=%s", file_path)
    return url


async def persist_existing_asset_url(
    url: str,
    *key_parts: str,
    download_name: str | None = None,
    delete_local: bool = False,
) -> str:
    text = (url or "").strip()
    if not text:
        return text
    if not is_oss_enabled() or is_oss_url(text):
        return text

    from utils.asset_directory_utils import resolve_app_path_to_filesystem

    local_path = resolve_app_path_to_filesystem(text)
    if not local_path or not os.path.isfile(local_path):
        if os.path.isfile(text):
            local_path = text
        else:
            return text
    return await persist_local_path(
        local_path,
        build_object_key(*key_parts),
        download_name=download_name,
        delete_local=delete_local,
    )


async def persist_generated_image(local_path: str) -> str:
    """Upload a generated/uploaded image and drop the local copy."""
    if not is_oss_enabled() or not local_path or not os.path.isfile(local_path):
        return local_path
    from api.v1.auth.context import get_current_owner_id
    import uuid

    owner = get_current_owner_id() or "shared"
    ext = os.path.splitext(local_path)[1] or ".png"
    url = await persist_local_path(
        local_path,
        build_object_key(OSS_AREA_IMAGES, str(owner), f"{uuid.uuid4()}{ext}"),
        delete_local=True,
    )
    LOGGER.info("[oss] persisted generated image url=%s", url)
    return url


async def persist_export_file(local_path: str) -> str:
    from api.v1.auth.context import get_current_owner_id

    owner = get_current_owner_id() or "shared"
    name = os.path.basename(local_path)
    return await persist_local_path(
        local_path,
        build_object_key(OSS_AREA_EXPORTS, str(owner), name),
        download_name=name,
        delete_local=True,
    )


async def delete_by_url(url: str) -> None:
    if not is_oss_enabled() or not is_oss_url(url):
        return
    key = object_key_from_url(url)
    if not key:
        return
    try:
        await asyncio.to_thread(_delete_object_sync, key)
    except Exception:
        LOGGER.warning("[oss] failed to delete object url=%s", url, exc_info=True)
