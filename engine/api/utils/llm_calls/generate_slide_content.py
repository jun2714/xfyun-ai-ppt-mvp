import copy
import json
import logging
import re
from datetime import datetime
from typing import Optional

from llmai import get_client
from llmai.shared import JSONSchemaResponse, Message, SystemMessage, UserMessage

from models.presentation_layout import SlideLayoutModel
from models.presentation_outline_model import SlideOutlineModel
from utils.llm_client_error_handler import handle_llm_client_exceptions
from utils.llm_config import get_llm_config
from utils.llm_provider import get_model
from utils.llm_utils import DisconnectChecker, generate_structured_with_schema_retries
from utils.template_text_capacity import locked_text_fits_field
from utils.schema_utils import (
    add_field_in_schema,
    ensure_array_schemas_have_items,
    remove_fields_from_schema,
)

logger = logging.getLogger(__name__)
SLIDE_CONTENT_FRESH_ATTEMPTS = 2

SLIDE_CONTENT_SYSTEM_PROMPT = """
You will be given slide content and response schema.
You need to generate structured content json based on the schema.

# Steps
1. Analyze the content.
2. Analyze the response schema.
3. Generate structured content json based on the schema.
4. Generate speaker note if required.
5. Provide structured content json as output.

# General Rules
- Follow language guidelines.
- Slide Language is authoritative when it is explicitly set. If slide content
  or user instructions request a different language, ignore that conflicting
  language request unless Slide Language says auto-detect.
- Speaker notes must be plain text (no markdown).
- Never exceed max character limits; do not clip mid-sentence to fit—rephrase instead.
- Do not use emojis or $schema fields.
- Follow the intended outcome of user instructions when they do not conflict with Slide
  Language; do not generalize or expand their scope.
- Apply slide-specific instructions only to the exact slide mentioned (first/second/last/named) and only once.
- Do not apply patterns across multiple slides unless explicitly requested.
- If instructions are ambiguous, use the most direct interpretation without extending scope.
- Treat chart, layout, styling, positioning, and other visual instructions as production
  controls. Honor them through the selected schema, but never emit those instructions or
  meta-commentary as a title, body, label, table cell, or speaker note.
- Output fields must contain only audience-facing content and data. For chart fields,
  populate the requested labels, series, and values rather than text such as "create a
  bar chart" or "show this data as a graph".
- The text between SLIDE CONTENT markers is the complete and exclusive factual source
  for audience-facing text on this slide. Do not import facts, labels, choices, or examples
  from another slide.
- Do not invent extra audience-facing items merely to fill a layout. If the schema
  cannot represent the supplied content faithfully, fail validation instead of padding
  it with duplicated or newly authored content.

# Machine Content Contract Rules
- A MACHINE CONTENT CONTRACT may be supplied after the visible slide content. It is hidden
  production metadata. Never copy field names, activity ids, answer keys, semantic labels,
  teacher notes, or other contract metadata into visible slide text unless the visible
  SLIDE CONTENT already contains that audience-facing information.
- If preserve_visible_copy=true, the teacher has already approved the visible wording.
  You are a schema mapper, not a copywriter: copy every audience-facing phrase from
  SLIDE CONTENT verbatim into suitable editable text fields. Do not paraphrase, shorten,
  summarize, translate, synonymize, beautify, add a new heading, or invent filler. Keep
  punctuation, questions, invitations, surprise hooks and action wording unchanged. You
  may still author image_prompt/icon_query fields and the speaker note. Do not add markdown
  emphasis inside locked visible copy unless it was already present in SLIDE CONTENT.
- teaching_goal and teacher_note preserve classroom intent; teacher_note is for the speaker
  note, not the slide body.
- When a MACHINE CONTENT CONTRACT is present, this is a preschool classroom slide. Preserve
  the child-facing sense of wonder already written in SLIDE CONTENT. A question, invitation,
  mystery, role-play line, sound cue, or action prompt must not be flattened into a generic
  adult label such as “种子”, “学做”, “认识…”, “游戏时间”, or “总结”.
- For preschool slides, supporting copy should be something a 3-6 year-old can immediately
  observe, say, choose, imitate, or do. Avoid adjective-only lists, textbook definitions,
  adult report language, empty slogans, and repeated sentence patterns across the deck.
- Do not make every text field verbose just because the template has space. Large preschool
  type and one strong idea are better than filling every placeholder.
- required_asset_semantics is authoritative for image meaning. When the response schema has
  image_prompt fields, prompts must depict those exact required objects/features and must not
  substitute unrelated objects just because they are visually attractive. Include the exact
  required semantic phrase verbatim in at least one relevant image_prompt so the downstream
  semantic preflight can verify coverage before any paid image request is made.
- Preschool image_prompt fields should describe a specific delightful story moment, not a
  generic object catalogue: warm bright premium picture-book illustration, clear large subject,
  friendly emotion, simple readable composition, and one visually surprising action or clue.
  Keep real scientific features accurate. Never ask for black abstract textures, corporate
  stock-photo styling, horror, text, letters, numbers, labels, logos, watermarks or pseudo-text.
- activity_id and answer_key are consistency locks. For relationship=question, do not reveal
  answer_key in visible content or image prompts unless SLIDE CONTENT explicitly reveals it.
  For relationship=reveal, keep the generated content and imagery consistent with answer_key.
- interaction_type describes how the teacher and children use the page; preserve it in the
  speaker note when useful, but do not expose the metadata label itself.

{markdown_emphasis_rules}

{user_instructions}

{tone_instructions}

{verbosity_instructions}

{output_fields_instructions}
"""


SLIDE_CONTENT_USER_PROMPT = """
# Current Date and Time:
{current_date_time}

# Icon Query And Image Prompt Language:
Chinese

# Image Prompt Contract:
- Write image_prompt fields in Chinese.
- Image prompt language and slide visible language are independent.
- Image prompts describe visuals only. Never request visible text, letters, numbers,
  labels, captions, answers, logos, watermarks, signatures, or pseudo-text.
- Put every audience-facing title, label, option, answer, and annotation in editable
  slide text fields supplied by the response schema, never inside an image prompt.
- If people appear in the image, they must all be Chinese people with East Asian /
  Chinese facial features, clothing, and classroom/life context suitable for Chinese
  kindergarten teaching. Do not depict Western / Caucasian people.
- Prefer warm, bright, premium child-friendly Chinese picture-book illustration for teaching
  slides. Show a concrete story moment or action whenever the lesson content allows it, with
  a large clear subject and uncluttered composition. Avoid generic stock images and abstract
  black decorative textures.

# Slide Language:
{language}

{slide_number_section}
# SLIDE CONTENT: START
{content}
# SLIDE CONTENT: END

# MACHINE CONTENT CONTRACT: START
{content_contract}
# MACHINE CONTENT CONTRACT: END
"""

ASSET_ONLY_FIELDS = ["__image_url__", "__icon_url__"]
AUTO_DETECT_LANGUAGE_INSTRUCTION = (
    "auto-detect from the slide content and use the same language as the slide content"
)

# Structured generation still decides which template field receives each phrase. For
# reviewed kindergarten copy we deterministically put the exact outline phrases back into
# the generated audience-facing string slots afterwards. This removes the second model's
# opportunity to silently rewrite a teacher-approved outline while retaining its useful
# schema mapping and image-prompt work.
_NON_AUDIENCE_STRING_KEYS = {
    "__speaker_note__",
    "__content_contract__",
    "image_prompt",
    "__image_prompt__",
    "icon_query",
    "__icon_query__",
    "image_url",
    "__image_url__",
    "icon_url",
    "__icon_url__",
    "url",
    "prompt",
    "query",
    "type",
    "charttype",
    "chart_type",
    "color",
    "colors",
    "axiscolor",
    "axis_color",
    "gridcolor",
    "grid_color",
    "legendcolor",
    "legend_color",
}


def _resolve_prompt_language(language: Optional[str]) -> str:
    if language is None:
        return AUTO_DETECT_LANGUAGE_INSTRUCTION
    s = str(language).strip()
    if not s:
        return AUTO_DETECT_LANGUAGE_INSTRUCTION
    if s.lower() in {"auto", "auto-detect"}:
        return AUTO_DETECT_LANGUAGE_INSTRUCTION
    return s


def _get_schema_markdown(response_schema: Optional[dict]) -> str:
    if not response_schema:
        return "- Follow the provided response schema strictly."
    try:
        schema_text = json.dumps(response_schema, ensure_ascii=False)
    except Exception:
        return "- Follow the provided response schema strictly."
    return f"- Follow this response schema exactly: {schema_text}"


def get_system_prompt(
    tone: Optional[str] = None,
    verbosity: Optional[str] = None,
    instructions: Optional[str] = None,
    response_schema: Optional[dict] = None,
):
    markdown_emphasis_rules = (
        "- Use markdown emphasis only when it does not conflict with a locked "
        "preserve_visible_copy contract."
    )

    user_instructions = f"# User Instructions:\n{instructions}" if instructions else ""
    tone_instructions = (
        f"# Tone Instructions:\nMake slide as {tone} as possible." if tone else ""
    )

    verbosity_instructions = ""
    if verbosity:
        verbosity_instructions = "# Verbosity Instructions:\n"
        if verbosity == "concise":
            verbosity_instructions += "Make slide as concise as possible."
        elif verbosity == "standard":
            verbosity_instructions += "Make slide as standard as possible."
        elif verbosity == "text-heavy":
            verbosity_instructions += "Make slide as text-heavy as possible."

    output_fields_instructions = "# Output Fields:\n" + _get_schema_markdown(
        response_schema
    )

    return SLIDE_CONTENT_SYSTEM_PROMPT.format(
        markdown_emphasis_rules=markdown_emphasis_rules,
        user_instructions=user_instructions,
        tone_instructions=tone_instructions,
        verbosity_instructions=verbosity_instructions,
        output_fields_instructions=output_fields_instructions,
    )


def _get_slide_number_section(slide_number: Optional[int]) -> str:
    if slide_number is None:
        return ""
    return f"# Slide Number:\n{slide_number}\n"


def _serialize_content_contract(content_contract: Optional[dict]) -> str:
    if not content_contract:
        return "None"
    try:
        return json.dumps(content_contract, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "None"


def get_user_prompt(
    outline: str,
    language: Optional[str],
    slide_number: Optional[int] = None,
    content_contract: Optional[dict] = None,
):
    return SLIDE_CONTENT_USER_PROMPT.format(
        current_date_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        language=_resolve_prompt_language(language),
        slide_number_section=_get_slide_number_section(slide_number),
        content=outline,
        content_contract=_serialize_content_contract(content_contract),
    )


def get_messages(
    outline: str,
    language: Optional[str],
    tone: Optional[str] = None,
    verbosity: Optional[str] = None,
    instructions: Optional[str] = None,
    response_schema: Optional[dict] = None,
    *,
    slide_number: Optional[int] = None,
    content_contract: Optional[dict] = None,
) -> list[Message]:

    return [
        SystemMessage(
            content=get_system_prompt(
                tone,
                verbosity,
                instructions,
                response_schema,
            ),
        ),
        UserMessage(
            content=get_user_prompt(
                outline,
                language,
                slide_number,
                content_contract,
            ),
        ),
    ]


def _schema_has_content_fields(response_schema: Optional[dict]) -> bool:
    if not isinstance(response_schema, dict):
        return False

    properties = response_schema.get("properties")
    return isinstance(properties, dict) and bool(properties)


def _uses_cjk_typography(language: Optional[str]) -> bool:
    normalized = str(language or "").strip().casefold()
    return any(
        token in normalized
        for token in ("chinese", "中文", "简体", "繁体", "japanese", "日文", "korean", "韩文")
    )


def _apply_language_text_limits(value, use_cjk_limits: bool):
    if isinstance(value, list):
        return [_apply_language_text_limits(item, use_cjk_limits) for item in value]
    if not isinstance(value, dict):
        return value
    result = {
        key: _apply_language_text_limits(child, use_cjk_limits)
        for key, child in value.items()
        if key not in {"x-cjk-max-length", "x-text-boxes"}
    }
    cjk_limit = value.get("x-cjk-max-length")
    if use_cjk_limits and isinstance(cjk_limit, int) and cjk_limit > 0:
        current = result.get("maxLength")
        result["maxLength"] = min(current, cjk_limit) if isinstance(current, int) else cjk_limit
        if isinstance(result.get("minLength"), int):
            result["minLength"] = min(result["minLength"], result["maxLength"])
    return result


def _prepare_response_schema(
    json_schema: Optional[dict], language: Optional[str] = None
) -> Optional[dict]:
    if not isinstance(json_schema, dict):
        return None

    response_schema = remove_fields_from_schema(
        copy.deepcopy(json_schema), ASSET_ONLY_FIELDS
    )
    response_schema = _apply_language_text_limits(
        response_schema, _uses_cjk_typography(language)
    )
    if not _schema_has_content_fields(response_schema):
        return None

    if response_schema.get("type") != "object":
        response_schema["type"] = "object"

    response_schema = add_field_in_schema(
        response_schema,
        {
            "__speaker_note__": {
                "type": "string",
                "minLength": 20,
                "maxLength": 500,
                "description": "Speaker note for the slide",
            }
        },
        True,
    )
    return ensure_array_schemas_have_items(response_schema)


def _strip_outline_markup(line: str) -> str:
    value = line.strip()
    value = re.sub(r"^#{1,6}\s+", "", value)
    value = re.sub(r"^(?:[-*+•]|\d+[.)])\s+", "", value)
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    value = re.sub(r"__(.*?)__", r"\1", value)
    return value.strip()


def _outline_visible_lines(content: str) -> list[str]:
    return [
        cleaned
        for raw in (content or "").splitlines()
        if (cleaned := _strip_outline_markup(raw))
    ]


def _is_non_audience_string_key(key: str | None) -> bool:
    if not key:
        return False
    normalized = key.strip().casefold()
    if normalized.startswith("__"):
        return True
    return normalized in _NON_AUDIENCE_STRING_KEYS


def _audience_string_slots(
    value,
    *,
    parent_key: str | None = None,
):
    slots: list[tuple[object, object]] = []
    if _is_non_audience_string_key(parent_key):
        return slots
    if isinstance(value, dict):
        for key, child in value.items():
            if _is_non_audience_string_key(str(key)):
                continue
            if isinstance(child, str):
                slots.append((value, key))
            elif isinstance(child, (dict, list)):
                slots.extend(_audience_string_slots(child, parent_key=str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, str):
                slots.append((value, index))
            elif isinstance(child, (dict, list)):
                slots.extend(_audience_string_slots(child, parent_key=parent_key))
    return slots


def _schema_audience_slots(value, schema: dict):
    """Enumerate editable strings in template order, never model JSON key order."""
    slots = []
    if isinstance(value, dict):
        for key, child_schema in (schema.get("properties") or {}).items():
            if key not in value or _is_non_audience_string_key(key):
                continue
            child = value[key]
            if isinstance(child, str):
                slots.append((value, key, child_schema))
            elif isinstance(child, (dict, list)):
                slots.extend(_schema_audience_slots(child, child_schema))
    elif isinstance(value, list):
        child_schema = schema.get("items") or {}
        for index, child in enumerate(value):
            if isinstance(child, str):
                slots.append((value, index, child_schema))
            elif isinstance(child, (dict, list)):
                slots.extend(_schema_audience_slots(child, child_schema))
    return slots


def _apply_locked_visible_copy(
    generated: dict, outline_content: str, response_schema: Optional[dict] = None
) -> dict:
    """Restore teacher-reviewed copy without another LLM request.

    With a template schema, preserve field order and declared capacities independently
    of the provider's JSON serialization order. Blank unused fields and never truncate
    reviewed phrases. The schema-less legacy path retains its original behavior.
    """
    lines = _outline_visible_lines(outline_content)
    if not lines:
        return generated
    if response_schema is not None:
        ordered_slots = _schema_audience_slots(generated, response_schema)
        memo = {}

        def allocate(slot_index, line_index):
            if line_index == len(lines):
                return (0, [])
            if slot_index == len(ordered_slots):
                return None
            state = (slot_index, line_index)
            if state in memo:
                return memo[state]
            field_schema = ordered_slots[slot_index][2]
            best = None
            # Prefer one phrase per field. Combine adjacent phrases only if needed
            # and the declared capacity permits it. A 3-character badge is never
            # allowed to swallow a 13-character reviewed title.
            for count in range(1, len(lines) - line_index + 1):
                phrase = "\n".join(lines[line_index:line_index + count])
                if not locked_text_fits_field(phrase, field_schema):
                    break
                tail = allocate(slot_index + 1, line_index + count)
                if tail is not None:
                    candidate = (tail[0] + (count - 1) ** 2,
                                 [(slot_index, phrase)] + tail[1])
                    if best is None or candidate[0] < best[0]:
                        best = candidate
            skipped = allocate(slot_index + 1, line_index)
            if skipped is not None and (best is None or skipped[0] < best[0]):
                best = skipped
            memo[state] = best
            return best

        allocation = allocate(0, 0)
        if allocation is None:
            raise ValueError("Reviewed outline does not fit the selected template text capacities")
        for container, key in _audience_string_slots(generated):
            container[key] = ""
        for slot_index, phrase in allocation[1]:
            container, key, _limit = ordered_slots[slot_index]
            container[key] = phrase
        return generated
    slots = _audience_string_slots(generated)
    if not slots:
        return generated

    if len(slots) >= len(lines):
        for index, (container, key) in enumerate(slots):
            container[key] = lines[index] if index < len(lines) else ""
        return generated

    for index, (container, key) in enumerate(slots):
        if index < len(slots) - 1:
            container[key] = lines[index]
        else:
            container[key] = "\n".join(lines[index:])
    return generated


def reviewed_outline_fits_schema(schema: dict, outline_content: str) -> bool:
    """Use the same deterministic allocator before any paid slide-content call."""
    skeleton = _schema_fallback_value(schema)
    if not isinstance(skeleton, dict):
        return False
    try:
        _apply_locked_visible_copy(skeleton, outline_content, schema)
    except ValueError:
        return False
    return True


def _fallback_image_prompt(content_contract: Optional[dict]) -> str:
    contract = content_contract or {}
    semantic_phrases = [
        str(value).strip()
        for value in (contract.get("required_asset_semantics") or [])
        if str(value).strip()
    ]
    descriptions = [
        str(item.get("description") or item.get("semantic_label") or "").strip()
        for item in (contract.get("asset_contracts") or [])
        if isinstance(item, dict)
        and str(item.get("description") or item.get("semantic_label") or "").strip()
    ]
    subject = "；".join(semantic_phrases or descriptions) or "与本页教学内容一致的幼儿绘本场景"
    detail = descriptions[0] if descriptions else subject
    return (
        f"{subject}。{detail}。温暖明亮的中国幼儿绘本插画，主体清楚，构图简洁，"
        "适合4至6岁儿童观察，不含文字、字母、数字、标志或水印。"
    )


def _schema_fallback_value(
    schema: object,
    *,
    field_name: str = "",
    content_contract: Optional[dict] = None,
):
    """Materialize a conservative schema-shaped value without another model call.

    This is a last-resort circuit breaker for one failed slide. Audience strings are
    replaced with the reviewed outline immediately afterwards, while image prompts and
    teacher notes retain the machine contract. A provider error therefore cannot erase
    every other successfully generated page.
    """
    if not isinstance(schema, dict):
        return ""
    for union_key in ("oneOf", "anyOf"):
        choices = schema.get(union_key)
        if isinstance(choices, list):
            choice = next(
                (item for item in choices if isinstance(item, dict) and item.get("type") != "null"),
                choices[0] if choices else {},
            )
            return _schema_fallback_value(
                choice,
                field_name=field_name,
                content_contract=content_contract,
            )

    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return copy.deepcopy(enum[0])
    if "const" in schema:
        return copy.deepcopy(schema["const"])

    value_type = schema.get("type")
    if isinstance(value_type, list):
        value_type = next((item for item in value_type if item != "null"), "string")
    if value_type is None:
        if isinstance(schema.get("properties"), dict):
            value_type = "object"
        elif isinstance(schema.get("items"), dict):
            value_type = "array"
        else:
            value_type = "string"

    if value_type == "object":
        properties = schema.get("properties") or {}
        return {
            key: _schema_fallback_value(
                child_schema,
                field_name=str(key),
                content_contract=content_contract,
            )
            for key, child_schema in properties.items()
            if isinstance(child_schema, dict)
        }
    if value_type == "array":
        items = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        minimum = max(1, int(schema.get("minItems") or 0))
        maximum = int(schema.get("maxItems") or minimum)
        count = min(minimum, maximum) if maximum >= 0 else minimum
        return [
            _schema_fallback_value(
                items,
                field_name=field_name,
                content_contract=content_contract,
            )
            for _ in range(max(0, count))
        ]
    if value_type == "boolean":
        return bool(schema.get("default", False))
    if value_type in {"integer", "number"}:
        value = schema.get("default", schema.get("minimum", 0))
        return int(value) if value_type == "integer" else float(value)
    if value_type == "null":
        return None

    normalized_key = field_name.strip().casefold()
    contract = content_contract or {}
    if normalized_key in {"image_prompt", "__image_prompt__"}:
        return _fallback_image_prompt(contract)
    if normalized_key == "__speaker_note__":
        return str(contract.get("teacher_note") or "请按已确认的大纲引导幼儿观察和互动。")
    if normalized_key in {"icon_query", "__icon_query__"}:
        return "儿童课堂"
    default = schema.get("default")
    return str(default) if default is not None else ""


def _build_schema_fallback(
    response_schema: dict,
    outline_content: str,
    content_contract: Optional[dict],
) -> dict:
    fallback = _schema_fallback_value(
        response_schema,
        content_contract=content_contract,
    )
    if not isinstance(fallback, dict):
        fallback = {}
    return _apply_locked_visible_copy(fallback, outline_content, response_schema)


def _image_prompt_slots(value) -> list[tuple[dict, str]]:
    slots: list[tuple[dict, str]] = []
    if isinstance(value, list):
        for child in value:
            slots.extend(_image_prompt_slots(child))
        return slots
    if not isinstance(value, dict):
        return slots
    for key, child in value.items():
        if key in {"image_prompt", "__image_prompt__"} and isinstance(child, str):
            slots.append((value, key))
        elif isinstance(child, (dict, list)):
            slots.extend(_image_prompt_slots(child))
    return slots


def _ensure_required_asset_semantics(
    generated: dict,
    content_contract: Optional[dict],
) -> dict:
    """Deterministically enforce the planner's required visual subjects."""
    required = [
        str(value).strip()
        for value in ((content_contract or {}).get("required_asset_semantics") or [])
        if str(value).strip()
    ]
    if not required:
        return generated
    slots = _image_prompt_slots(generated)
    if not slots:
        return generated
    combined = "\n".join(container[key] for container, key in slots)
    missing = [semantic for semantic in required if semantic not in combined]
    for index, semantic in enumerate(missing):
        container, key = slots[index % len(slots)]
        prompt = container[key].strip()
        container[key] = f"{prompt}。必须清楚呈现：{semantic}" if prompt else semantic
    return generated


async def get_slide_content_from_type_and_outline(
    slide_layout: SlideLayoutModel,
    outline: SlideOutlineModel,
    language: Optional[str],
    tone: Optional[str] = None,
    verbosity: Optional[str] = None,
    instructions: Optional[str] = None,
    *,
    slide_number: Optional[int] = None,
    disconnect_checker: Optional[DisconnectChecker] = None,
):
    response_schema = _prepare_response_schema(slide_layout.json_schema, language)
    if response_schema is None:
        return {}

    client = get_client(config=get_llm_config())
    model = get_model()
    contract_data = (
        outline.content_contract.model_dump(mode="json")
        if outline.content_contract is not None
        else None
    )

    try:
        response_format = JSONSchemaResponse(
            name="response",
            json_schema=response_schema,
            strict=False,
        )
        messages = get_messages(
            outline.content,
            language,
            tone,
            verbosity,
            instructions,
            response_schema,
            slide_number=slide_number,
            content_contract=contract_data,
        )

        generated = None
        last_error: Optional[Exception] = None
        for attempt in range(1, SLIDE_CONTENT_FRESH_ATTEMPTS + 1):
            try:
                generated = await generate_structured_with_schema_retries(
                    client,
                    model,
                    messages=messages,
                    response_format=response_format,
                    json_schema=response_schema,
                    strict=False,
                    validate_schema=True,
                    disconnect_checker=disconnect_checker,
                )
                break
            except Exception as error:
                last_error = error
                logger.warning(
                    "Slide %s content attempt %s/%s failed: %s",
                    slide_number or "?",
                    attempt,
                    SLIDE_CONTENT_FRESH_ATTEMPTS,
                    error,
                )
        if generated is None:
            logger.error(
                "Slide %s content provider failed after %s fresh attempts; using reviewed-copy fallback: %s",
                slide_number or "?",
                SLIDE_CONTENT_FRESH_ATTEMPTS,
                last_error,
            )
            generated = _build_schema_fallback(
                slide_layout.json_schema,
                outline.content,
                contract_data,
            )
        generated = _ensure_required_asset_semantics(generated, contract_data)
        if (
            outline.content_contract is not None
            and outline.content_contract.preserve_visible_copy
        ):
            generated = _apply_locked_visible_copy(
                generated, outline.content, slide_layout.json_schema
            )
        if contract_data:
            # Keep hidden planning semantics attached to the materialized slide.
            # Asset planning receives SlideModel objects, not PresentationOutlineModel,
            # so this is the bridge that lets later quality gates enforce the same
            # lesson intent without re-inferring it from visible copy.
            generated["__content_contract__"] = contract_data
        if (
            outline.content_contract is not None
            and outline.content_contract.teacher_note
        ):
            generated["__speaker_note__"] = outline.content_contract.teacher_note
        return generated

    except Exception as e:
        raise handle_llm_client_exceptions(e)
