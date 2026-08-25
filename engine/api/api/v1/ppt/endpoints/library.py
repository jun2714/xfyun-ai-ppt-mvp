from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.v1.auth.context import get_current_owner_id, get_current_owner_is_admin
from models.sql.ppt_library_item import PptLibraryItem
from services.database import async_session_maker, get_async_session
from services.library_edit_copy import create_presentation_from_layouts
from services.export_task_service import EXPORT_TASK_SERVICE
from templates.fonts_and_slides_preview import render_pptx_slides_to_images
from templates.v2.models.elements import Position
from templates.v2.models.layouts import (
    Component,
    RawSlideLayouts,
    SlideLayout,
    SlideLayouts,
)
from utils.asset_directory_utils import (
    absolute_fastapi_asset_url,
    resolve_app_path_to_filesystem,
)
from utils.cjk_fonts import CJK_PREVIEW_MARK, ensure_cjk_preview_font, has_preview_cjk_font
from utils.datetime_utils import get_current_utc_datetime
from utils.get_env import get_app_data_directory_env, get_temp_directory_env, is_disable_auth_enabled
from utils.oss_storage import (
    PPTX_CONTENT_TYPE,
    delete_by_url,
    is_oss_enabled,
    is_oss_url,
    library_object_key,
    materialize_url_to_file,
    persist_local_path,
    sign_get_url,
)
from utils.pptx_slide_preview import (
    count_pptx_slides,
    has_slide_screenshot_backend,
    render_pptx_slide_previews,
    render_pptx_via_libreoffice,
    render_pptx_via_office,
)

from utils.library_tags import (
    LIBRARY_AGE_GROUPS,
    LIBRARY_CATEGORIES,
    LIBRARY_SCENES,
    LIBRARY_SEASONS,
    guess_library_tags,
    normalize_library_choice,
)

LOGGER = logging.getLogger(__name__)
LIBRARY_ROUTER = APIRouter(prefix="/library", tags=["PPT Library"])
LARGE_FILE_LAYOUT_LIMIT = 25 * 1024 * 1024
PREVIEW_MAX_WIDTH = 1280
PREVIEW_JPEG_QUALITY = 72
_PREVIEW_LOCKS: dict[str, asyncio.Lock] = {}
SCREENSHOT_ENGINES = {"office", "libreoffice"}
PENDING_PREVIEW_STATUSES = {"pending", "generating"}


class LibraryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: Optional[str] = None
    category: str
    age_group: str
    season: str = "不限"
    scene: str = "其他"
    page_count: int
    thumbnail: Optional[str] = None
    slide_image_urls: list[str] = []
    download_count: int
    editable: bool = False
    visibility: str = "official"
    preview_status: str = "ready"
    preview_engine: str = ""
    created_at: object
    updated_at: object


class LibraryListResponse(BaseModel):
    items: list[LibraryItemResponse]
    total: int
    can_manage: bool = False


class LibraryCloneResponse(BaseModel):
    presentation_id: str
    title: str
    id: str = ""


class LibraryDownloadResponse(BaseModel):
    url: str


def _library_root() -> str:
    app_data = get_app_data_directory_env()
    if not app_data:
        raise HTTPException(status_code=500, detail="APP_DATA_DIRECTORY is not configured")
    root = os.path.join(app_data, "library")
    os.makedirs(root, exist_ok=True)
    return root


def _working_dir(item_id: str) -> str:
    """Scratch directory for parse/preview. Permanent files go to OSS when configured."""
    if is_oss_enabled():
        root = os.path.join(
            get_temp_directory_env() or tempfile.gettempdir(),
            "ppt-library",
            item_id,
        )
    else:
        root = os.path.join(_library_root(), item_id)
    os.makedirs(root, exist_ok=True)
    return root


def _item_dir(item_id: str) -> str:
    return _working_dir(item_id)


def can_manage_library() -> bool:
    """Only TeachNova admin can publish/delete library originals."""
    if get_current_owner_is_admin():
        return True
    return is_disable_auth_enabled() and get_current_owner_id() is None


def _require_library_admin() -> None:
    if not can_manage_library():
        raise HTTPException(status_code=403, detail="只有管理员可以维护素材库")


def _to_app_data_url(abs_path: str) -> str:
    app_data = os.path.realpath(get_app_data_directory_env() or "")
    real = os.path.realpath(abs_path)
    rel = os.path.relpath(real, app_data).replace(os.sep, "/")
    return absolute_fastapi_asset_url(f"/app_data/{rel}")


def _safe_original_name(filename: str | None) -> str:
    name = os.path.basename(filename or "case.pptx")
    if not name.lower().endswith(".pptx"):
        name = f"{name}.pptx"
    return name


def _assert_pptx_file(path: str) -> None:
    with open(path, "rb") as handle:
        magic = handle.read(4)
    if magic[:2] != b"PK":
        raise HTTPException(status_code=400, detail="不是有效的 PPTX 文件，请重新上传")


def _readable_asset_url(url: str | None) -> str | None:
    if not url:
        return url
    if is_oss_url(url):
        return sign_get_url(url)
    return url


def _fallback_layouts(raw_layouts: RawSlideLayouts) -> SlideLayouts:
    generated: list[SlideLayout] = []
    for index, raw in enumerate(raw_layouts.layouts):
        elements = list(raw.elements or [])
        components = (
            [
                Component(
                    id=f"source_canvas_{index + 1}",
                    description="Editable source canvas preserved from the uploaded slide.",
                    position=Position(x=0, y=0),
                    elements=elements,
                )
            ]
            if elements
            else []
        )
        generated.append(
            SlideLayout(
                id=raw.id or f"source_layout_{index + 1}",
                description="Fallback layout preserving the uploaded source slide.",
                components=components,
            )
        )
    return SlideLayouts(layouts=generated)


def _slide_urls_of(item: PptLibraryItem) -> list[str]:
    assets = item.assets if isinstance(item.assets, dict) else {}
    raw = assets.get("slide_image_urls")
    urls = [url for url in raw if isinstance(url, str) and url.strip()] if isinstance(raw, list) else []
    thumbnail = item.thumbnail if isinstance(item.thumbnail, str) else ""
    if not urls and thumbnail.strip():
        return [thumbnail.strip()]
    return urls


def _item_response(item: PptLibraryItem, include_slides: bool = True) -> LibraryItemResponse:
    slide_urls = _slide_urls_of(item)
    now = get_current_utc_datetime()
    assets = item.assets if isinstance(item.assets, dict) else {}
    status = assets.get("preview_status")
    if not isinstance(status, str) or not status.strip():
        status = "ready" if (slide_urls or item.thumbnail) else "pending"
    engine = assets.get("preview_engine")
    if not isinstance(engine, str):
        engine = ""
    return LibraryItemResponse(
        id=str(item.id),
        title=item.title or "",
        description=item.description,
        category=item.category or "其他",
        age_group=item.age_group or "混龄",
        season=getattr(item, "season", None) or "不限",
        scene=getattr(item, "scene", None) or "其他",
        page_count=int(item.page_count or len(slide_urls) or 0),
        thumbnail=_readable_asset_url(item.thumbnail or (slide_urls[0] if slide_urls else None)),
        slide_image_urls=[_readable_asset_url(url) or url for url in slide_urls] if include_slides else [],
        download_count=int(item.download_count or 0),
        editable=bool(item.layouts),
        visibility=getattr(item, "visibility", None) or "official",
        preview_status=status,
        preview_engine=engine,
        created_at=item.created_at or now,
        updated_at=item.updated_at or now,
    )


def _preview_assets(
    pptx_url: str,
    slide_urls: list[str],
    preview_engine: str,
    preview_status: str = "ready",
) -> dict:
    assets = {
        "pptx_url": pptx_url,
        "slide_image_urls": slide_urls,
        "preview_engine": preview_engine,
        "preview_status": preview_status,
    }
    if has_preview_cjk_font() or preview_engine in SCREENSHOT_ENGINES:
        assets["preview_charset"] = CJK_PREVIEW_MARK
    return assets


def _preview_lock(item_id: str) -> asyncio.Lock:
    lock = _PREVIEW_LOCKS.get(item_id)
    if lock is None:
        lock = asyncio.Lock()
        _PREVIEW_LOCKS[item_id] = lock
    return lock


async def _save_upload_file(file: UploadFile, dest: str) -> int:
    size = 0
    with open(dest, "wb") as handle:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            handle.write(chunk)
    return size


async def _library_html_font_paths(pptx_abs: str, item_dir: str) -> list[str]:
    from templates.pptx_font_utils import extract_raw_fonts_and_embedded_details

    font_dir = os.path.join(item_dir, "embedded-fonts")
    os.makedirs(font_dir, exist_ok=True)
    _raw, _details, embedded = await asyncio.to_thread(
        extract_raw_fonts_and_embedded_details, pptx_abs, font_dir
    )
    paths = [path for path in embedded if path and os.path.isfile(path)]
    cjk_path = ensure_cjk_preview_font()
    if cjk_path:
        paths.append(cjk_path)
    return paths


async def _render_library_slides(
    pptx_abs: str, item_dir: str, prefer_html: bool
) -> tuple[str, list[str]]:
    office_paths = await asyncio.to_thread(render_pptx_via_office, pptx_abs, item_dir)
    if office_paths:
        return "office", office_paths
    lo_dir = os.path.join(item_dir, "lo-screens")
    lo_paths = await asyncio.to_thread(render_pptx_via_libreoffice, pptx_abs, lo_dir)
    if lo_paths:
        return "libreoffice", lo_paths
    if prefer_html:
        try:
            font_paths = await _library_html_font_paths(pptx_abs, item_dir)
            html_paths = list(
                await asyncio.wait_for(
                    render_pptx_slides_to_images(pptx_abs, font_paths, None, LOGGER),
                    timeout=420,
                )
            )
            if html_paths:
                return "html", html_paths
        except Exception:
            LOGGER.exception("[ppt.library] HTML slide preview failed path=%s", pptx_abs)
    fallback_paths = await asyncio.to_thread(
        render_pptx_slide_previews, pptx_abs, item_dir
    )
    return "fallback", fallback_paths


def _compress_preview_image(source_path: str, dest_path: str) -> str:
    from PIL import Image

    image = Image.open(source_path)
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")
    elif image.mode != "RGB":
        image = image.convert("RGB")
    image.thumbnail((PREVIEW_MAX_WIDTH, int(PREVIEW_MAX_WIDTH * 9 / 16)))
    image.save(dest_path, "JPEG", quality=PREVIEW_JPEG_QUALITY, optimize=True)
    return dest_path


async def _persist_slide_images(
    rendered_paths: list[str],
    item_dir: str,
    category: str,
    item_id: str,
) -> list[str]:
    slide_urls: list[str] = []
    for index, source_path in enumerate(rendered_paths, start=1):
        dest = os.path.join(item_dir, f"slide_{index}.jpg")
        try:
            await asyncio.to_thread(_compress_preview_image, source_path, dest)
        except Exception:
            dest = os.path.join(item_dir, f"slide_{index}.png")
            if os.path.abspath(source_path) != os.path.abspath(dest):
                shutil.copy2(source_path, dest)
        filename = os.path.basename(dest)
        if is_oss_enabled():
            slide_urls.append(
                await persist_local_path(
                    dest,
                    library_object_key(category, item_id, filename.replace("slide_", "preview_")),
                    delete_local=True,
                )
            )
        else:
            slide_urls.append(_to_app_data_url(dest))
    return slide_urls


async def _commit_item_preview(
    item: PptLibraryItem,
    sql_session: AsyncSession,
    *,
    slide_urls: list[str],
    preview_engine: str,
    preview_status: str,
    page_count: int = 0,
    old_slide_urls: list[str] | None = None,
) -> PptLibraryItem:
    assets = dict(item.assets if isinstance(item.assets, dict) else {})
    assets["slide_image_urls"] = slide_urls
    assets["pptx_url"] = item.pptx_path
    assets["preview_engine"] = preview_engine
    assets["preview_status"] = preview_status
    if has_preview_cjk_font() or preview_engine in SCREENSHOT_ENGINES:
        assets["preview_charset"] = CJK_PREVIEW_MARK
    item.assets = assets
    item.page_count = page_count or item.page_count or len(slide_urls)
    item.thumbnail = slide_urls[0] if slide_urls else item.thumbnail
    item.updated_at = get_current_utc_datetime()
    sql_session.add(item)
    await sql_session.commit()
    await sql_session.refresh(item)
    for url in old_slide_urls or []:
        if isinstance(url, str) and url not in slide_urls:
            await delete_by_url(url)
    return item


async def _parse_library_layouts(pptx_abs: str, slide_count: int):
    layouts_json = None
    raw_layouts_json = None
    try:
        pptx_json = await EXPORT_TASK_SERVICE.convert_pptx_to_json(pptx_abs)
        raw_layouts = RawSlideLayouts.model_validate(pptx_json.model_dump(mode="json"))
        if slide_count:
            raw_layouts = RawSlideLayouts(layouts=raw_layouts.layouts[:slide_count])
        raw_layouts_json = raw_layouts.model_dump(mode="json", exclude_none=True)
        if raw_layouts.layouts:
            layouts_json = _fallback_layouts(raw_layouts).model_dump(
                mode="json", exclude_none=True
            )
    except Exception:
        LOGGER.exception("[ppt.library] PPTX layout parse failed path=%s", pptx_abs)
    return layouts_json, raw_layouts_json


async def _reload_library_item(
    sql_session: AsyncSession, item_id: str, fallback: PptLibraryItem
) -> PptLibraryItem:
    try:
        await sql_session.rollback()
    except Exception:
        LOGGER.exception("[ppt.library] rollback failed item_id=%s", item_id)
    reloaded = await sql_session.get(PptLibraryItem, item_id)
    return reloaded or fallback


async def _hydrate_missing_preview(
    item: PptLibraryItem,
    sql_session: AsyncSession,
) -> PptLibraryItem:
    item_id = str(item.id)
    async with _preview_lock(item_id):
        fresh = await sql_session.get(PptLibraryItem, item_id)
        if not fresh:
            return item
        item = fresh
        assets = item.assets if isinstance(item.assets, dict) else {}
        existing_urls = [
            url
            for url in (assets.get("slide_image_urls") or [])
            if isinstance(url, str) and url.strip()
        ]
        engine = str(assets.get("preview_engine") or "")
        already_cjk = assets.get("preview_charset") == CJK_PREVIEW_MARK
        if existing_urls and engine in SCREENSHOT_ENGINES:
            return item
        can_upgrade_screenshot = engine in {"html", "fallback", "", "pending"} and (
            has_slide_screenshot_backend()
        )
        if existing_urls and not can_upgrade_screenshot and (already_cjk or not has_preview_cjk_font()):
            return item
        if not item.pptx_path:
            return item
        item_dir = _working_dir(item.id)
        pptx_abs = os.path.join(item_dir, "original.pptx")
        try:
            assets = dict(assets)
            assets["preview_status"] = "generating"
            item.assets = assets
            sql_session.add(item)
            await sql_session.commit()
            await sql_session.refresh(item)

            await materialize_url_to_file(item.pptx_path, pptx_abs)
            page_count = await asyncio.to_thread(count_pptx_slides, pptx_abs)
            old_slides = existing_urls

            if not existing_urls:
                fallback_dir = os.path.join(item_dir, "fallback-screens")
                fallback_paths = await asyncio.to_thread(
                    render_pptx_slide_previews, pptx_abs, fallback_dir
                )
                fallback_urls = await _persist_slide_images(
                    fallback_paths, item_dir, item.category, item.id
                )
                if fallback_urls:
                    item = await _commit_item_preview(
                        item,
                        sql_session,
                        slide_urls=fallback_urls,
                        preview_engine="fallback",
                        preview_status="generating",
                        page_count=page_count,
                    )
                    existing_urls = fallback_urls
                    old_slides = fallback_urls

            preview_engine, rendered_paths = await _render_library_slides(
                pptx_abs, item_dir, prefer_html=True
            )
            if preview_engine in SCREENSHOT_ENGINES or (
                preview_engine == "html" and rendered_paths
            ):
                slide_urls = await _persist_slide_images(
                    rendered_paths, item_dir, item.category, item.id
                )
                if slide_urls:
                    item = await _commit_item_preview(
                        item,
                        sql_session,
                        slide_urls=slide_urls,
                        preview_engine=preview_engine,
                        preview_status="ready",
                        page_count=page_count,
                        old_slide_urls=old_slides,
                    )
                elif existing_urls:
                    current_engine = "fallback"
                    if isinstance(item.assets, dict):
                        current_engine = str(item.assets.get("preview_engine") or "fallback")
                    item = await _commit_item_preview(
                        item,
                        sql_session,
                        slide_urls=existing_urls,
                        preview_engine=current_engine,
                        preview_status="ready",
                        page_count=page_count,
                    )
                else:
                    assets = dict(item.assets if isinstance(item.assets, dict) else {})
                    assets["preview_status"] = "failed"
                    item.assets = assets
                    sql_session.add(item)
                    await sql_session.commit()
                    await sql_session.refresh(item)
                    return item
            elif existing_urls:
                current_engine = "fallback"
                if isinstance(item.assets, dict):
                    current_engine = str(item.assets.get("preview_engine") or "fallback")
                item = await _commit_item_preview(
                    item,
                    sql_session,
                    slide_urls=existing_urls,
                    preview_engine=current_engine,
                    preview_status="ready",
                    page_count=page_count,
                )
            else:
                assets = dict(item.assets if isinstance(item.assets, dict) else {})
                assets["preview_status"] = "failed"
                item.assets = assets
                sql_session.add(item)
                await sql_session.commit()
                await sql_session.refresh(item)
                return item

            if not item.layouts:
                file_size = os.path.getsize(pptx_abs) if os.path.isfile(pptx_abs) else 0
                if file_size <= LARGE_FILE_LAYOUT_LIMIT:
                    layouts_json, raw_layouts_json = await _parse_library_layouts(
                        pptx_abs, page_count or len(_slide_urls_of(item))
                    )
                    if layouts_json:
                        item.layouts = layouts_json
                        item.raw_layouts = raw_layouts_json
                        item.updated_at = get_current_utc_datetime()
                        sql_session.add(item)
                        await sql_session.commit()
                        await sql_session.refresh(item)
        except Exception:
            LOGGER.exception("[ppt.library] hydrate preview failed item_id=%s", item.id)
            item = await _reload_library_item(sql_session, item.id, item)
            try:
                assets = dict(item.assets if isinstance(item.assets, dict) else {})
                if not _slide_urls_of(item):
                    assets["preview_status"] = "failed"
                    item.assets = assets
                    sql_session.add(item)
                    await sql_session.commit()
                    await sql_session.refresh(item)
            except Exception:
                LOGGER.exception("[ppt.library] mark preview failed item_id=%s", item.id)
        finally:
            if is_oss_enabled():
                shutil.rmtree(item_dir, ignore_errors=True)
        return item


async def _generate_library_preview_job(item_id: str) -> None:
    async with async_session_maker() as session:
        item = await session.get(PptLibraryItem, item_id)
        if not item:
            return
        try:
            await _hydrate_missing_preview(item, session)
        except Exception:
            LOGGER.exception("[ppt.library] background preview failed item_id=%s", item_id)


async def _persist_original_pptx(pptx_abs: str, category: str, item_id: str, title: str) -> str:
    if is_oss_enabled():
        return await persist_local_path(
            pptx_abs,
            library_object_key(category, item_id, "original.pptx"),
            content_type=PPTX_CONTENT_TYPE,
            download_name=_safe_original_name(f"{title}.pptx"),
            delete_local=True,
        )
    return _to_app_data_url(pptx_abs)


@LIBRARY_ROUTER.get("", response_model=LibraryListResponse)
@LIBRARY_ROUTER.get("/", response_model=LibraryListResponse, include_in_schema=False)
async def list_library_items(
    background_tasks: BackgroundTasks,
    response: Response,
    q: Optional[str] = None,
    category: Optional[str] = None,
    age_group: Optional[str] = None,
    season: Optional[str] = None,
    scene: Optional[str] = None,
    scope: str = Query("official"),
    include_slides: bool = Query(False),
    sql_session: AsyncSession = Depends(get_async_session),
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    statement = select(PptLibraryItem).order_by(PptLibraryItem.created_at.desc())
    result = await sql_session.execute(statement)
    items = list(result.scalars().all())
    keyword = (q or "").strip().lower()
    owner_id = get_current_owner_id()
    filtered: list[PptLibraryItem] = []
    for item in items:
        visibility = getattr(item, "visibility", None) or "official"
        if scope == "mine":
            if visibility != "personal" or getattr(item, "created_by", None) != owner_id:
                continue
        elif scope != "all":
            if visibility == "personal":
                continue
        if category and category != "全部" and item.category != category:
            continue
        if age_group and age_group != "全部" and item.age_group != age_group:
            continue
        if season and season != "全部" and getattr(item, "season", "不限") != season:
            continue
        if scene and scene != "全部" and getattr(item, "scene", "其他") != scene:
            continue
        if keyword:
            haystack = f"{item.title} {item.description or ''} {getattr(item, 'scene', '')} {getattr(item, 'season', '')}".lower()
            if keyword not in haystack:
                continue
        filtered.append(item)
    queued = 0
    for item in filtered:
        if queued >= 8:
            break
        assets = item.assets if isinstance(item.assets, dict) else {}
        status = str(assets.get("preview_status") or "")
        if not _slide_urls_of(item) and status in PENDING_PREVIEW_STATUSES:
            background_tasks.add_task(_generate_library_preview_job, str(item.id))
            queued += 1
    return LibraryListResponse(
        items=[_item_response(item, include_slides=include_slides) for item in filtered],
        total=len(filtered),
        can_manage=can_manage_library(),
    )


@LIBRARY_ROUTER.post("", response_model=LibraryItemResponse)
@LIBRARY_ROUTER.post("/", response_model=LibraryItemResponse, include_in_schema=False)
async def create_library_item(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(""),
    category: str = Form(""),
    age_group: str = Form(""),
    season: str = Form(""),
    scene: str = Form(""),
    sql_session: AsyncSession = Depends(get_async_session),
):
    is_admin = can_manage_library()
    filename = (file.filename or "").lower()
    if not filename.endswith(".pptx"):
        raise HTTPException(status_code=400, detail="请上传 .pptx 文件")
    guessed = guess_library_tags(file.filename, title)
    title = (title or "").strip() or guessed["title"]
    if not title:
        raise HTTPException(status_code=400, detail="请填写案例标题")
    category = normalize_library_choice(category, LIBRARY_CATEGORIES, guessed["category"])
    age_group = normalize_library_choice(age_group, LIBRARY_AGE_GROUPS, guessed["age_group"])
    season = normalize_library_choice(season, LIBRARY_SEASONS, guessed["season"])
    scene = normalize_library_choice(scene, LIBRARY_SCENES, guessed["scene"])

    item_id = str(uuid.uuid4())
    item_dir = _working_dir(item_id)
    pptx_abs = os.path.join(item_dir, "original.pptx")
    size = await _save_upload_file(file, pptx_abs)
    if size <= 0:
        shutil.rmtree(item_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="上传文件为空")
    try:
        _assert_pptx_file(pptx_abs)
    except HTTPException:
        shutil.rmtree(item_dir, ignore_errors=True)
        raise

    try:
        page_count = await asyncio.to_thread(count_pptx_slides, pptx_abs)
    except Exception:
        LOGGER.exception("[ppt.library] count slides failed item_id=%s", item_id)
        page_count = 0

    pptx_url = ""
    try:
        pptx_url = await _persist_original_pptx(pptx_abs, category, item_id, title)
    except Exception:
        LOGGER.exception("[ppt.library] persist original failed item_id=%s", item_id)
        if is_oss_enabled():
            shutil.rmtree(item_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail="案例未能写入对象存储")
        raise HTTPException(status_code=500, detail="案例未能保存到服务器")
    finally:
        if is_oss_enabled():
            shutil.rmtree(item_dir, ignore_errors=True)

    if not pptx_url:
        raise HTTPException(status_code=500, detail="案例未能写入存储")

    item = PptLibraryItem(
        id=item_id,
        title=title,
        description=description.strip() or None,
        category=category,
        age_group=age_group,
        season=season,
        scene=scene,
        page_count=page_count,
        thumbnail=None,
        pptx_path=pptx_url,
        layouts=None,
        raw_layouts=None,
        assets=_preview_assets(pptx_url, [], "pending", preview_status="pending"),
        visibility="official" if is_admin else "personal",
        created_by=get_current_owner_id(),
    )
    sql_session.add(item)
    await sql_session.commit()
    await sql_session.refresh(item)
    background_tasks.add_task(_generate_library_preview_job, item.id)
    return _item_response(item)



@LIBRARY_ROUTER.put("/{item_id}", response_model=LibraryItemResponse)
async def update_library_item(
    item_id: str,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    age_group: Optional[str] = Form(None),
    season: Optional[str] = Form(None),
    scene: Optional[str] = Form(None),
    sql_session: AsyncSession = Depends(get_async_session),
):
    item = await sql_session.get(PptLibraryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="案例不存在")
    visibility = getattr(item, "visibility", None) or "official"
    owner_id = get_current_owner_id()
    if visibility == "official":
        _require_library_admin()
    elif getattr(item, "created_by", None) != owner_id and not can_manage_library():
        raise HTTPException(status_code=403, detail="只能修改自己上传的课件")

    next_title = (title or "").strip() or item.title
    next_description = item.description if description is None else (description.strip() or None)
    next_category = item.category
    if category:
        next_category = category if category in LIBRARY_CATEGORIES else "其他"
    next_age_group = item.age_group
    if age_group:
        next_age_group = age_group if age_group in LIBRARY_AGE_GROUPS else "混龄"
    next_season = getattr(item, "season", None) or "不限"
    if season:
        next_season = season if season in LIBRARY_SEASONS else "不限"
    next_scene = getattr(item, "scene", None) or "其他"
    if scene:
        next_scene = scene if scene in LIBRARY_SCENES else "其他"

    old_urls = [item.pptx_path, item.thumbnail]
    assets = item.assets if isinstance(item.assets, dict) else {}
    old_slides = assets.get("slide_image_urls")
    if isinstance(old_slides, list):
        old_urls.extend(old_slides)
    pptx_asset = assets.get("pptx_url")
    if isinstance(pptx_asset, str):
        old_urls.append(pptx_asset)

    if file is not None and file.filename:
        filename = (file.filename or "").lower()
        if not filename.endswith(".pptx"):
            raise HTTPException(status_code=400, detail="请上传 .pptx 文件")

        item_dir = _working_dir(item.id)
        pptx_abs = os.path.join(item_dir, "original.pptx")
        size = await _save_upload_file(file, pptx_abs)
        if size <= 0:
            shutil.rmtree(item_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail="上传文件为空")
        try:
            _assert_pptx_file(pptx_abs)
        except HTTPException:
            shutil.rmtree(item_dir, ignore_errors=True)
            raise

        try:
            page_count = await asyncio.to_thread(count_pptx_slides, pptx_abs)
        except Exception:
            LOGGER.exception("[ppt.library] count slides failed item_id=%s", item.id)
            page_count = 0

        pptx_url = ""
        try:
            pptx_url = await _persist_original_pptx(pptx_abs, next_category, item.id, next_title)
        except Exception:
            LOGGER.exception("[ppt.library] replace persist failed item_id=%s", item.id)
            if is_oss_enabled():
                shutil.rmtree(item_dir, ignore_errors=True)
                raise HTTPException(status_code=500, detail="案例未能写入对象存储")
            raise HTTPException(status_code=500, detail="案例未能保存到服务器")
        finally:
            if is_oss_enabled():
                shutil.rmtree(item_dir, ignore_errors=True)

        if not pptx_url:
            raise HTTPException(status_code=500, detail="案例未能写入存储")

        item.page_count = page_count
        item.thumbnail = None
        item.pptx_path = pptx_url
        item.layouts = None
        item.raw_layouts = None
        item.assets = _preview_assets(pptx_url, [], "pending", preview_status="pending")
        for url in old_urls:
            if isinstance(url, str) and url != pptx_url:
                await delete_by_url(url)
        background_tasks.add_task(_generate_library_preview_job, item.id)

    item.title = next_title
    item.description = next_description
    item.category = next_category
    item.age_group = next_age_group
    item.season = next_season
    item.scene = next_scene
    item.updated_at = get_current_utc_datetime()
    sql_session.add(item)
    await sql_session.commit()
    await sql_session.refresh(item)
    return _item_response(item)


@LIBRARY_ROUTER.get("/{item_id}", response_model=LibraryItemResponse)
async def get_library_item(
    item_id: str,
    background_tasks: BackgroundTasks,
    sql_session: AsyncSession = Depends(get_async_session),
):
    item = await sql_session.get(PptLibraryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="案例不存在")
    assets = item.assets if isinstance(item.assets, dict) else {}
    engine = str(assets.get("preview_engine") or "")
    status = str(assets.get("preview_status") or "")
    urls = _slide_urls_of(item)
    if not urls:
        background_tasks.add_task(_generate_library_preview_job, item.id)
        return _item_response(item)
    should_upgrade = engine in {"html", "fallback", ""} and has_slide_screenshot_backend()
    if should_upgrade:
        if status != "generating":
            assets = dict(assets)
            assets["preview_status"] = "generating"
            item.assets = assets
            sql_session.add(item)
            await sql_session.commit()
            await sql_session.refresh(item)
        background_tasks.add_task(_generate_library_preview_job, item.id)
    return _item_response(item)


@LIBRARY_ROUTER.get("/{item_id}/download")
async def download_library_item(
    item_id: str,
    sql_session: AsyncSession = Depends(get_async_session),
):
    item = await sql_session.get(PptLibraryItem, item_id)
    if not item or not item.pptx_path:
        raise HTTPException(status_code=404, detail="案例不存在")

    download_name = _safe_original_name(f"{item.title}.pptx")
    tmp_dir = None
    abs_path = None
    source = item.pptx_path
    if is_oss_url(source) or (
        isinstance(source, str) and source.startswith(("http://", "https://"))
    ):
        tmp_dir = tempfile.mkdtemp(prefix="ppt-dl-")
        abs_path = os.path.join(tmp_dir, "original.pptx")
        try:
            await materialize_url_to_file(source, abs_path)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            LOGGER.exception("[ppt.library] download materialize failed item_id=%s", item_id)
            raise HTTPException(status_code=404, detail="原文件不存在或无法读取") from None
    else:
        abs_path = resolve_app_path_to_filesystem(source)
        if not abs_path or not os.path.isfile(abs_path):
            raise HTTPException(status_code=404, detail="原文件不存在")

    with open(abs_path, "rb") as handle:
        magic = handle.read(4)
    if magic[:2] != b"PK":
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="原文件已损坏，请重新上传 PPTX")

    item.download_count = int(item.download_count or 0) + 1
    item.updated_at = get_current_utc_datetime()
    sql_session.add(item)
    await sql_session.commit()

    cleanup = BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True) if tmp_dir else None
    return FileResponse(
        abs_path,
        media_type=PPTX_CONTENT_TYPE,
        filename=download_name,
        background=cleanup,
    )


@LIBRARY_ROUTER.post("/{item_id}/clone", response_model=LibraryCloneResponse)
async def clone_library_item_for_edit(
    item_id: str,
    sql_session: AsyncSession = Depends(get_async_session),
):
    item = await sql_session.get(PptLibraryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="案例不存在")
    if not item.layouts:
        raise HTTPException(
            status_code=400,
            detail="该案例暂不支持在线编辑，请直接下载原件",
        )
    try:
        presentation, slides = create_presentation_from_layouts(
            title=item.title,
            description=item.description,
            layouts=item.layouts,
            assets=item.assets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sql_session.add(presentation)
    sql_session.add_all(slides)
    await sql_session.commit()
    await sql_session.refresh(presentation)
    presentation_id = str(presentation.id)
    return LibraryCloneResponse(
        presentation_id=presentation_id,
        id=presentation_id,
        title=presentation.title or item.title,
    )


@LIBRARY_ROUTER.delete("/{item_id}", status_code=204)
async def delete_library_item(
    item_id: str,
    sql_session: AsyncSession = Depends(get_async_session),
):
    item = await sql_session.get(PptLibraryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="案例不存在")
    visibility = getattr(item, "visibility", None) or "official"
    owner_id = get_current_owner_id()
    if visibility == "personal":
        if getattr(item, "created_by", None) != owner_id and not can_manage_library():
            raise HTTPException(status_code=403, detail="只能删除自己上传的课件")
    else:
        _require_library_admin()
    urls_to_delete = [item.pptx_path, item.thumbnail]
    assets = item.assets if isinstance(item.assets, dict) else {}
    slide_urls = assets.get("slide_image_urls")
    if isinstance(slide_urls, list):
        urls_to_delete.extend(slide_urls)
    pptx_asset = assets.get("pptx_url")
    if isinstance(pptx_asset, str):
        urls_to_delete.append(pptx_asset)
    item_dir = None
    app_data = get_app_data_directory_env()
    if app_data:
        item_dir = os.path.join(app_data, "library", item.id)
    await sql_session.delete(item)
    await sql_session.commit()
    if item_dir:
        shutil.rmtree(item_dir, ignore_errors=True)
    for url in urls_to_delete:
        if isinstance(url, str):
            await delete_by_url(url)
    return None
