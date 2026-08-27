import copy
import json
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
from utils.schema_utils import (
    add_field_in_schema,
    ensure_array_schemas_have_items,
    remove_fields_from_schema,
)

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
- teaching_goal and teacher_note preserve classroom intent; teacher_note is for the speaker
  note, not the slide body.
- required_asset_semantics is authoritative for image meaning. When the response schema has
  image_prompt fields, prompts must depict those exact required objects/features and must not
  substitute unrelated objects just because they are visually attractive.
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
- Prefer warm, child-friendly Chinese illustration style for teaching slides.

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
        "- Strictly use markdown to emphasize important points, by bolding or "
        "italicizing the part of text."
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
        if key != "x-cjk-max-length"
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
        if (
            outline.content_contract is not None
            and outline.content_contract.teacher_note
        ):
            generated["__speaker_note__"] = outline.content_contract.teacher_note
        return generated

    except Exception as e:
        raise handle_llm_client_exceptions(e)
