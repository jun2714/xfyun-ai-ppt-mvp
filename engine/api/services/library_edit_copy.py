from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import uuid
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel
from models.sql.template_v2 import TemplateV2
from utils.asset_directory_utils import (
    absolute_fastapi_asset_url,
    resolve_app_path_to_filesystem,
)
from utils.get_env import get_app_data_directory_env

LOGGER = logging.getLogger(__name__)
EDIT_COPY_MARK = "编辑副本"
SLIDE_FILE_RE = re.compile(r"^slide_(\d+)\.(jpg|jpeg|png)$", re.IGNORECASE)


def is_library_edit_copy_name(name: Optional[str]) -> bool:
    return EDIT_COPY_MARK in (name or "")


def clean_edit_copy_title(name: Optional[str]) -> str:
    text = re.sub(r"[（(]\s*编辑副本\s*[）)]", "", name or "").strip()
    return text or (name or "").strip() or "未命名课件"


def layout_payload_from_source(layouts: Any) -> dict[str, Any]:
    payload = copy.deepcopy(layouts)
    if isinstance(payload, dict) and isinstance(payload.get("layouts"), list):
        return payload
    if isinstance(payload, list):
        return {"layouts": payload}
    raise ValueError("课件版式数据无效，无法创建可编辑项目")


def slide_image_urls_from_assets(assets: Any) -> list[str]:
    if not isinstance(assets, dict):
        return []
    raw = assets.get("slide_image_urls")
    if not isinstance(raw, list):
        return []
    return [url.strip() for url in raw if isinstance(url, str) and url.strip()]


def _to_app_data_url(abs_path: str) -> str:
    app_data = os.path.realpath(get_app_data_directory_env() or "")
    real = os.path.realpath(abs_path)
    rel = os.path.relpath(real, app_data).replace(os.sep, "/")
    if rel.startswith(".."):
        raise ValueError("资源不在 app_data 目录内")
    return absolute_fastapi_asset_url(f"/app_data/{rel}")


def presentation_asset_dir(presentation_id: str) -> str:
    app_data = get_app_data_directory_env()
    if not app_data:
        raise ValueError("APP_DATA_DIRECTORY is not configured")
    item_id = str(presentation_id).strip()
    if not item_id or "/" in item_id or "\\" in item_id or item_id in {".", ".."}:
        raise ValueError("无效的项目编号")
    root = os.path.realpath(os.path.join(app_data, "presentations"))
    dest = os.path.realpath(os.path.join(root, item_id))
    if os.path.commonpath([root, dest]) != root:
        raise ValueError("无效的项目资源目录")
    os.makedirs(dest, exist_ok=True)
    return dest


def remove_presentation_asset_dir(presentation_id: str) -> None:
    app_data = get_app_data_directory_env()
    if not app_data:
        return
    root = os.path.realpath(os.path.join(app_data, "presentations"))
    dest = os.path.realpath(os.path.join(root, str(presentation_id)))
    try:
        if os.path.commonpath([root, dest]) != root:
            return
    except ValueError:
        return
    shutil.rmtree(dest, ignore_errors=True)


def rewrite_library_asset_refs(payload: Any, library_id: str, presentation_id: str) -> Any:
    library_id = str(library_id).strip()
    presentation_id = str(presentation_id).strip()
    if not library_id or not presentation_id:
        return payload
    text = json.dumps(payload, ensure_ascii=False)
    replacements = (
        (
            f"/ppt-api/app_data/library/{library_id}/",
            f"/ppt-api/app_data/presentations/{presentation_id}/",
        ),
        (
            f"/app_data/library/{library_id}/",
            f"/app_data/presentations/{presentation_id}/",
        ),
    )
    changed = False
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new)
            changed = True
    if not changed:
        return payload
    return json.loads(text)


def missing_library_file_paths(file_paths: Optional[list[str]]) -> list[str]:
    missing: list[str] = []
    for url in file_paths or []:
        if not isinstance(url, str) or "/app_data/library/" not in url:
            continue
        if not resolve_app_path_to_filesystem(url):
            missing.append(url)
    return missing


def discover_library_slide_files(library_id: str) -> list[str]:
    app_data = get_app_data_directory_env()
    if not app_data:
        return []
    item_id = str(library_id).strip()
    if not item_id or "/" in item_id or "\\" in item_id:
        return []
    item_dir = os.path.join(app_data, "library", item_id)
    if not os.path.isdir(item_dir):
        return []
    found: list[tuple[int, str]] = []
    for name in os.listdir(item_dir):
        match = SLIDE_FILE_RE.match(name)
        if not match:
            continue
        found.append((int(match.group(1)), os.path.join(item_dir, name)))
    found.sort(key=lambda item: item[0])
    return [path for _, path in found]


async def _copy_source_to_dest(source: str, dest: str) -> None:
    local = resolve_app_path_to_filesystem(source)
    if local and os.path.isfile(local):
        if os.path.abspath(local) != os.path.abspath(dest):
            shutil.copy2(local, dest)
        return
    if os.path.isfile(source):
        if os.path.abspath(source) != os.path.abspath(dest):
            shutil.copy2(source, dest)
        return
    from utils.oss_storage import materialize_url_to_file

    await materialize_url_to_file(source, dest)
    if not os.path.isfile(dest):
        raise FileNotFoundError(source)


async def snapshot_library_assets_for_presentation(
    *,
    presentation_id: str,
    library_id: Optional[str] = None,
    slide_urls: Optional[list[str]] = None,
    original_source: Optional[str] = None,
    layouts: Any = None,
    assets: Any = None,
) -> tuple[list[str], Any, Any]:
    """Copy library preview files into an independent presentation directory."""
    dest_dir: Optional[str] = None
    try:
        sources: list[str] = []
        if library_id:
            sources = discover_library_slide_files(library_id)
        if not sources:
            for url in slide_urls or []:
                local = resolve_app_path_to_filesystem(url)
                if local:
                    sources.append(local)
                else:
                    sources.append(url)
        if not sources:
            rewritten_layouts = rewrite_library_asset_refs(layouts, library_id or "", presentation_id)
            rewritten_assets = rewrite_library_asset_refs(assets, library_id or "", presentation_id)
            return [], rewritten_layouts, rewritten_assets

        dest_dir = presentation_asset_dir(presentation_id)

        copied_urls: list[str] = []
        for index, source in enumerate(sources, start=1):
            ext = os.path.splitext(str(source).split("?")[0])[1].lower() or ".jpg"
            if ext not in {".jpg", ".jpeg", ".png"}:
                ext = ".jpg"
            dest = os.path.join(dest_dir, f"slide_{index}{ext}")
            await _copy_source_to_dest(source, dest)
            if not os.path.isfile(dest):
                raise FileNotFoundError(f"未能复制第 {index} 页预览")
            copied_urls.append(_to_app_data_url(dest))

        if original_source:
            original_dest = os.path.join(dest_dir, "original.pptx")
            try:
                await _copy_source_to_dest(original_source, original_dest)
            except Exception:
                LOGGER.warning(
                    "[ppt.library] skip original.pptx copy presentation_id=%s",
                    presentation_id,
                    exc_info=True,
                )

        rewritten_layouts = rewrite_library_asset_refs(layouts, library_id or "", presentation_id)
        rewritten_assets = rewrite_library_asset_refs(assets, library_id or "", presentation_id)
        if isinstance(rewritten_assets, dict):
            rewritten_assets = dict(rewritten_assets)
            rewritten_assets["slide_image_urls"] = copied_urls
        return copied_urls, rewritten_layouts, rewritten_assets
    except Exception:
        if dest_dir:
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise


def create_presentation_from_layouts(
    *,
    title: str,
    description: Optional[str],
    layouts: Any,
    assets: Any = None,
    file_paths: Optional[list[str]] = None,
    presentation_id: Optional[uuid.UUID] = None,
) -> tuple[PresentationModel, list[SlideModel]]:
    layout_payload = layout_payload_from_source(layouts)
    layout_list = [item for item in layout_payload["layouts"] if isinstance(item, dict)]
    if not layout_list:
        raise ValueError("课件没有可编辑的页面")

    presentation_id = presentation_id or uuid.uuid4()
    layout_payload["name"] = str(presentation_id)
    fonts = None
    if isinstance(assets, dict) and isinstance(assets.get("fonts"), dict):
        fonts = {
            name.strip(): url.strip()
            for name, url in assets["fonts"].items()
            if isinstance(name, str) and isinstance(url, str) and name.strip() and url.strip()
        } or None

    image_urls = file_paths if file_paths is not None else slide_image_urls_from_assets(assets)
    presentation = PresentationModel(
        id=presentation_id,
        version=PresentationVersion.V2_STANDARD,
        content=(description or title or "").strip(),
        n_slides=len(layout_list),
        language="Chinese",
        title=title,
        file_paths=image_urls or None,
        layout=layout_payload,
        fonts=fonts,
        include_title_slide=False,
    )
    slides = [
        SlideModel(
            presentation=presentation_id,
            layout_group=str(presentation_id),
            layout=str(layout.get("id") or f"layout_{index + 1}"),
            index=index,
            content={},
            speaker_note="",
            ui=copy.deepcopy(layout),
        )
        for index, layout in enumerate(layout_list)
    ]
    return presentation, slides


async def persist_presentation_from_template(
    sql_session: AsyncSession,
    template: TemplateV2,
    *,
    title: Optional[str] = None,
    layouts: Any = None,
    delete_template: bool = True,
    commit: bool = True,
) -> PresentationModel:
    presentation_id = uuid.uuid4()
    source_layouts = template.layouts if layouts is None else layouts
    source_assets = template.assets
    copied_urls, source_layouts, source_assets = await snapshot_library_assets_for_presentation(
        presentation_id=str(presentation_id),
        slide_urls=slide_image_urls_from_assets(source_assets),
        layouts=source_layouts,
        assets=source_assets,
    )
    try:
        presentation, slides = create_presentation_from_layouts(
            title=clean_edit_copy_title(title or template.name),
            description=template.description,
            layouts=source_layouts,
            assets=source_assets,
            file_paths=copied_urls,
            presentation_id=presentation_id,
        )
        sql_session.add(presentation)
        sql_session.add_all(slides)
        if delete_template:
            await sql_session.delete(template)
        if commit:
            await sql_session.commit()
            await sql_session.refresh(presentation)
        return presentation
    except Exception:
        remove_presentation_asset_dir(str(presentation_id))
        raise


async def migrate_library_edit_copy_templates(sql_session: AsyncSession) -> int:
    """Move leftover library edit-copies out of 模板中心 into 我的项目."""
    result = await sql_session.execute(
        select(TemplateV2).where(TemplateV2.is_default == False)  # noqa: E712
    )
    templates = [
        template
        for template in result.scalars().all()
        if is_library_edit_copy_name(template.name)
    ]
    converted = 0
    for template in templates:
        presentation_id = uuid.uuid4()
        try:
            copied_urls, layouts, assets = await snapshot_library_assets_for_presentation(
                presentation_id=str(presentation_id),
                slide_urls=slide_image_urls_from_assets(template.assets),
                layouts=template.layouts,
                assets=template.assets,
            )
            presentation, slides = create_presentation_from_layouts(
                title=clean_edit_copy_title(template.name),
                description=template.description,
                layouts=layouts,
                assets=assets,
                file_paths=copied_urls,
                presentation_id=presentation_id,
            )
            sql_session.add(presentation)
            sql_session.add_all(slides)
            await sql_session.delete(template)
            converted += 1
        except Exception:
            remove_presentation_asset_dir(str(presentation_id))
            LOGGER.exception(
                "[ppt.library] failed to migrate edit-copy template id=%s name=%s",
                template.id,
                template.name,
            )
    if converted:
        await sql_session.commit()
        LOGGER.info("[ppt.library] migrated %s edit-copy templates into presentations", converted)
    return converted
