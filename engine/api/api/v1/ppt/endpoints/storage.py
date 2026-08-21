from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from utils.get_env import get_app_data_directory_env
from utils.oss_storage import is_oss_enabled, persist_export_file

STORAGE_ROUTER = APIRouter(prefix="/oss", tags=["OSS Storage"])


class PersistExportRequest(BaseModel):
    path: str


class PersistExportResponse(BaseModel):
    enabled: bool
    url: str | None = None


def _is_under_exports(path: str) -> bool:
    app_data = get_app_data_directory_env()
    if not app_data:
        return False
    exports_root = os.path.realpath(os.path.join(app_data, "exports"))
    try:
        real = os.path.realpath(path)
    except OSError:
        return False
    try:
        return os.path.commonpath([real, exports_root]) == exports_root
    except ValueError:
        return False


@STORAGE_ROUTER.post("/persist-export", response_model=PersistExportResponse)
async def persist_export_to_oss(body: PersistExportRequest):
    if not is_oss_enabled():
        return PersistExportResponse(enabled=False, url=None)
    if not body.path or not os.path.isfile(body.path):
        raise HTTPException(status_code=404, detail="导出文件不存在")
    if not _is_under_exports(body.path):
        raise HTTPException(status_code=400, detail="只能转存导出目录中的文件")
    url = await persist_export_file(body.path)
    return PersistExportResponse(enabled=True, url=url)
