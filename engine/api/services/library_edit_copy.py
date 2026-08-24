from __future__ import annotations

import copy
import logging
import re
import uuid
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel
from models.sql.template_v2 import TemplateV2

LOGGER = logging.getLogger(__name__)
EDIT_COPY_MARK = "编辑副本"


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


def create_presentation_from_layouts(
    *,
    title: str,
    description: Optional[str],
    layouts: Any,
    assets: Any = None,
) -> tuple[PresentationModel, list[SlideModel]]:
    layout_payload = layout_payload_from_source(layouts)
    layout_list = [item for item in layout_payload["layouts"] if isinstance(item, dict)]
    if not layout_list:
        raise ValueError("课件没有可编辑的页面")

    presentation_id = uuid.uuid4()
    layout_payload["name"] = str(presentation_id)
    fonts = None
    if isinstance(assets, dict) and isinstance(assets.get("fonts"), dict):
        fonts = {
            name.strip(): url.strip()
            for name, url in assets["fonts"].items()
            if isinstance(name, str) and isinstance(url, str) and name.strip() and url.strip()
        } or None

    image_urls = slide_image_urls_from_assets(assets)
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
    presentation, slides = create_presentation_from_layouts(
        title=clean_edit_copy_title(title or template.name),
        description=template.description,
        layouts=template.layouts if layouts is None else layouts,
        assets=template.assets,
    )
    sql_session.add(presentation)
    sql_session.add_all(slides)
    if delete_template:
        await sql_session.delete(template)
    if commit:
        await sql_session.commit()
        await sql_session.refresh(presentation)
    return presentation


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
        try:
            presentation, slides = create_presentation_from_layouts(
                title=clean_edit_copy_title(template.name),
                description=template.description,
                layouts=template.layouts,
                assets=template.assets,
            )
            sql_session.add(presentation)
            sql_session.add_all(slides)
            await sql_session.delete(template)
            converted += 1
        except Exception:
            LOGGER.exception(
                "[ppt.library] failed to migrate edit-copy template id=%s name=%s",
                template.id,
                template.name,
            )
    if converted:
        await sql_session.commit()
        LOGGER.info("[ppt.library] migrated %s edit-copy templates into presentations", converted)
    return converted
