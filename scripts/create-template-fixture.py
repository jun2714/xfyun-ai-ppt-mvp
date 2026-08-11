import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "engine" / "api"
sys.path.insert(0, str(API_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)
os.environ.setdefault(
    "APP_DATA_DIRECTORY",
    str((ROOT / os.environ.get("ENGINE_DATA_DIRECTORY", ".data/engine")).resolve()),
)

from api.v1.ppt.endpoints.presentation import (  # noqa: E402
    _hydrate_template_slide_ui,
    _template_slide_ui,
)
from models.sql.presentation import PresentationModel, PresentationVersion  # noqa: E402
from models.sql.slide import SlideModel  # noqa: E402
from models.sql.template_v2 import TemplateV2  # noqa: E402
from models.image_policy import ImagePolicy  # noqa: E402
from services.database import async_session_maker  # noqa: E402
from templates.v2.schema import get_template_schema  # noqa: E402
from utils.layout_compatibility import schema_contains_image_slot  # noqa: E402
from utils.llm_calls.generate_slide_content import _apply_language_text_limits  # noqa: E402


def bounded_text(field_name: str, schema: dict[str, Any], slide_number: int) -> str:
    field = field_name.casefold()
    if any(token in field for token in ("title", "heading", "headline", "header", "name")):
        base = f"快乐成长第{slide_number}站"
    elif any(token in field for token in ("label", "tag", "number", "index")):
        base = f"要点{slide_number}"
    elif any(token in field for token in ("quote", "message", "note")):
        base = "每一次发现都值得认真分享"
    else:
        base = "观察、交流并说出自己的新发现"
    minimum = int(schema.get("minLength", 1) or 1)
    maximum = int(schema.get("maxLength", max(len(base), minimum)) or len(base))
    value = base
    while len(value) < minimum:
        value += base
    return value[:maximum]


def schema_value(schema: Any, field_name: str, slide_number: int) -> Any:
    if not isinstance(schema, dict):
        return None
    if "default" in schema:
        return schema["default"]
    for choice_key in ("oneOf", "anyOf", "allOf"):
        choices = schema.get(choice_key)
        if isinstance(choices, list) and choices:
            return schema_value(choices[0], field_name, slide_number)
    if schema.get("enum"):
        return schema["enum"][0]
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), None)
    if schema_type == "object":
        return {
            name: schema_value(child, name, slide_number)
            for name, child in (schema.get("properties") or {}).items()
        }
    if schema_type == "array":
        minimum = int(schema.get("minItems", 1) or 1)
        maximum = int(schema.get("maxItems", max(minimum, 3)) or max(minimum, 3))
        count = min(max(minimum, 2), maximum)
        return [
            schema_value(schema.get("items") or {}, f"{field_name}_{index + 1}", slide_number)
            for index in range(count)
        ]
    if schema_type == "string":
        return bounded_text(field_name, schema, slide_number)
    if schema_type in {"integer", "number"}:
        return schema.get("minimum", slide_number)
    if schema_type == "boolean":
        return False
    return None


async def create_fixture(
    template_id: str,
    limit: int | None,
    title: str,
    passed_only: bool,
) -> uuid.UUID:
    async with async_session_maker() as session:
        template = await session.get(TemplateV2, template_id)
        if not template or not isinstance(template.layouts, dict):
            raise RuntimeError(f"template is unavailable: {template_id}")
        layout_payload = template.layouts
        schema_payload = get_template_schema(layout_payload)
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for source, generated in zip(
            layout_payload.get("layouts") or [], schema_payload["layouts"]
        ):
            metadata = source.get("metadata") or {}
            quality_status = metadata.get("qualityStatus") or metadata.get(
                "quality_status"
            )
            if passed_only and quality_status != "passed":
                continue
            schema = generated["schema"]
            if not schema_contains_image_slot(schema):
                candidates.append((source, _apply_language_text_limits(schema, True)))
        if limit:
            candidates = candidates[:limit]
        if not candidates:
            raise RuntimeError(f"template has no no-image layouts: {template_id}")

        presentation_id = uuid.uuid4()
        presentation = PresentationModel(
            id=presentation_id,
            version=PresentationVersion.V2_STANDARD,
            content="本地模板中文排版验收",
            n_slides=len(candidates),
            language="Chinese",
            title=title,
            layout=layout_payload,
            structure={"slides": list(range(len(candidates)))},
            image_policy=ImagePolicy.DISABLED,
        )
        slides: list[SlideModel] = []
        for index, (source, schema) in enumerate(candidates):
            content = schema_value(schema, "slide", index + 1)
            slide = SlideModel(
                presentation=presentation_id,
                layout_group=template_id,
                layout=source["id"],
                index=index,
                content=content,
                speaker_note="",
                ui=_template_slide_ui(layout_payload, source["id"]),
            )
            _hydrate_template_slide_ui(slide, layout_payload)
            slides.append(slide)
        session.add(presentation)
        session.add_all(slides)
        await session.commit()
        return presentation_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--title", default="模板中文排版验收")
    parser.add_argument(
        "--passed-only",
        action="store_true",
        help="only include layouts that already passed template visual QA",
    )
    args = parser.parse_args()
    presentation_id = asyncio.run(
        create_fixture(args.template, args.limit, args.title, args.passed_only)
    )
    print(json.dumps({"presentationId": str(presentation_id)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
