from typing import Optional

from llmai import get_client
from llmai.shared import JSONSchemaResponse, Message, SystemMessage, UserMessage
from models.presentation_layout import PresentationLayoutModel
from models.presentation_outline_model import PresentationOutlineModel
from utils.llm_config import get_llm_config
from utils.llm_client_error_handler import handle_llm_client_exceptions
from utils.llm_utils import DisconnectChecker, generate_structured_with_schema_retries
from utils.llm_provider import get_model
from utils.get_dynamic_models import get_presentation_structure_model_with_n_slides
from utils.layout_compatibility import (
    LayoutCompatibilityError,
    get_allowed_layout_indices_for_outline,
)
from utils.schema_utils import prepare_schema_for_validation
from models.presentation_structure_model import PresentationStructureModel


STRUCTURE_FROM_SLIDES_MARKDOWN_SYSTEM_PROMPT = """
You will be given available slide layouts and content for each slide.
You need to select a layout for each slide based on the mentioned guidelines.

# Steps
1. Analyze all available slide layouts.
2. Analyze content for each slide.
3. Select a layout for each slide one by one by following the selection rules.

# Analyzing Slide Layouts
- Identify what each layout contains based on provided schema markdown.

# Analyzing Content
- Identify how the content is structured.
- Identify if the content contains tables.

# Selection Rules
- Prefer image + text / card / process layouts for teaching, stories, crafts,
  activities, and young audiences. Do not invent chart layouts for classroom demos.
- If content contains a table with numeric data AND the user explicitly asked for a
  chart/graph/data report, select a graph layout. Otherwise prefer illustrated
  image layouts or simple cards that a child can understand at a glance.
- If content contains a text-only table, select a table layout.
- Don't select layout with image unless content contains image cues, the slide
  benefits from a scene illustration, or the user explicitly requests imagery.
  For educational/children content, prefer layouts that support images.
- Don't select table layout if content does not contain table.
- Treat each slide's supplied markdown as an authoritative, isolated content contract.
- Select a layout whose required field and item counts match that slide's content. Never
  choose a layout that would require inventing repeated items or copying content from
  another slide merely to satisfy its schema.
- Prefer distinct adjacent compositions. Reuse an adjacent layout only when the two
  slides genuinely have the same information structure and no other compatible layout exists.
- A short introductory slide with one headline and one message needs a title/emphasis
  composition, not a multi-item grid. A question or audience action needs a question/
  emphasis composition, not the preceding explanatory grid.

# Table Layout Selection Rules
- Must select table layout if the content contains table with text data.
- Must only select a layout with table if the table only contains text data.

# Graph Layout Selection Rules
- Charts are optional, not default. Prefer scene illustrations over bar/pie charts
  for kindergarten, preschool, craft, story, and activity decks.
- Must only select a layout with chart if BOTH are true:
  1) the content contains a table with numeric data, AND
  2) the user asked for charts/data visualization OR the deck is explicitly a
     metrics/report presentation.
- Do not select chart layouts merely because a slide mentions counts, ages, or
  simple numbers that could be shown as pictures or short text instead.
- Identify how many columns are present in the table.
- When a chart layout is required, select a layout that supports n-1 charts for n columns.
- Don't select metrics layout for content containing table with numeric data unless
  the user asked for metrics.

{user_intent}

# User Intent Rules
- Extract visual constraints from User Instructions and Original User Request; User Instructions win conflicts.
- The supplied slide count is authoritative. Slide numbers are one-based; "all" means every slide.
- Prefer exact chart types and image placements, reusing layouts if needed.
- Treat a numeric table on a chart-requested slide as chart data, not a request for a table-only layout.

# Output Rules: 
- One layout index for each slide.
- Example: [0, 1, 2, 3, 4]

{presentation_layout}
"""


GET_MESSAGES_SYSTEM_PROMPT = """
You're a professional presentation designer with creative freedom to design engaging presentations.

# DESIGN PHILOSOPHY
- Create visually compelling and varied presentations
- Match layout to content purpose and audience needs

# Layout Selection Guidelines
1. **Content-driven choices**: Let the slide's purpose guide layout selection
- Opening/closing → Title layouts
- Processes/workflows → Visual process layouts  
- Comparisons/contrasts → Side-by-side layouts
- Data/metrics → Chart/graph layouts ONLY when the user asked for charts or the deck is a data report; otherwise prefer illustrated image + text layouts
- Concepts/ideas → Image + text layouts
- Teaching/stories/crafts/young audiences → Illustrated image layouts, not charts
- Key insights → Emphasis layouts

2. **Visual variety**: Aim for diverse slide layouts across the presentation. 
- Don't use same layout for multiple slides unless necessary.
- Mix text-heavy and visual-heavy slides naturally
- Use your judgment on when repetition serves the content
- Balance information density across slides
- Adjacent slide layouts should be different unless instructed/necessary otherwise.

3. **Audience experience**: Consider how slides work together
- Create natural transitions between topics

4. **Table of contents**:
- Must only use table of contents layout if slide content contains table of contents.

{user_instruction_header}

Extract visual constraints from User Instructions and Original User Request; User
Instructions win conflicts. The supplied slide count is authoritative. Slide numbers are
one-based, and "all" or "every" includes the title slide. Prefer exact chart types and
image placements over variety, reusing layouts if needed. A numeric table on a
chart-requested slide is chart data, not a request for a table-only layout.

Select layout index for each of the {n_slides} slides based on what will best serve the presentation's goals.

"""


def get_messages(
    presentation_layout: PresentationLayoutModel,
    n_slides: int,
    data: str,
    instructions: Optional[str] = None,
    source_content: Optional[str] = None,
    allowed_layout_indices: Optional[list[list[int]]] = None,
) -> list[Message]:
    intent_sections = []
    if instructions:
        intent_sections.append(f"# User Instructions:\n{instructions}")
    if source_content:
        intent_sections.append(f"# Original User Request:\n{source_content}")
    system_prompt = GET_MESSAGES_SYSTEM_PROMPT.format(
        user_instruction_header="\n\n".join(intent_sections),
        n_slides=n_slides,
    )
    if allowed_layout_indices is not None:
        allowed_lines = "\n".join(
            f"- Slide {index + 1}: {indices}"
            for index, indices in enumerate(allowed_layout_indices)
        )
        system_prompt += (
            "\n# Hard Layout Compatibility\nChoose each slide only from its listed "
            "layout indices. These constraints were computed from capacity and media "
            f"metadata and are mandatory.\n{allowed_lines}\n"
        )

    return [
        SystemMessage(content=system_prompt),
        UserMessage(
            content=(
                f"{presentation_layout.to_string()}\n\n"
                "--------------------------------------\n\n"
                f"{data}"
            )
        ),
    ]


def get_messages_for_slides_markdown(
    presentation_layout: PresentationLayoutModel,
    n_slides: int,
    data: str,
    instructions: Optional[str] = None,
    source_content: Optional[str] = None,
    allowed_layout_indices: Optional[list[list[int]]] = None,
) -> list[Message]:
    intent_sections = []
    if instructions:
        intent_sections.append(f"# User Instructions:\n{instructions}")
    if source_content:
        intent_sections.append(f"# Original User Request:\n{source_content}")
    system_prompt = STRUCTURE_FROM_SLIDES_MARKDOWN_SYSTEM_PROMPT.format(
        user_intent="\n\n".join(intent_sections),
        presentation_layout=presentation_layout.to_string(with_schema=True),
    )
    if allowed_layout_indices is not None:
        allowed_lines = "\n".join(
            f"- Slide {index + 1}: {indices}"
            for index, indices in enumerate(allowed_layout_indices)
        )
        system_prompt += (
            "\n# Hard Layout Compatibility\nChoose each slide only from its listed "
            f"layout indices.\n{allowed_lines}\n"
        )

    return [SystemMessage(content=system_prompt), UserMessage(content=data)]


def _normalize_allowed_layout_indices(
    allowed_layout_indices: Optional[list[list[int]]],
    *,
    slide_count: int,
    layout_count: int,
) -> Optional[list[list[int]]]:
    if allowed_layout_indices is None:
        return None
    if len(allowed_layout_indices) != slide_count:
        raise LayoutCompatibilityError(
            "Hard layout compatibility count does not match the outline count"
        )

    normalized: list[list[int]] = []
    for slide_number, indices in enumerate(allowed_layout_indices, start=1):
        if not isinstance(indices, list):
            raise LayoutCompatibilityError(
                f"Slide {slide_number} hard layout choices must be a list",
                slide_number=slide_number,
            )
        unique_indices: list[int] = []
        for index in indices:
            if not isinstance(index, int) or isinstance(index, bool):
                raise LayoutCompatibilityError(
                    f"Slide {slide_number} hard layout choice must be an integer",
                    slide_number=slide_number,
                )
            if index < 0 or index >= layout_count:
                raise LayoutCompatibilityError(
                    f"Slide {slide_number} hard layout choice {index} is out of range",
                    slide_number=slide_number,
                )
            if index not in unique_indices:
                unique_indices.append(index)
        if not unique_indices:
            raise LayoutCompatibilityError(
                f"Slide {slide_number} has no allowed layout choices",
                slide_number=slide_number,
            )
        normalized.append(unique_indices)
    return normalized


def _validate_structure_against_allowed_layouts(
    structure: PresentationStructureModel,
    allowed_layout_indices: Optional[list[list[int]]],
) -> PresentationStructureModel:
    if allowed_layout_indices is None:
        return structure
    if len(structure.slides) != len(allowed_layout_indices):
        raise LayoutCompatibilityError(
            "Generated layout selection count does not match hard compatibility choices"
        )

    for slide_number, (selected, allowed) in enumerate(
        zip(structure.slides, allowed_layout_indices),
        start=1,
    ):
        if selected not in allowed:
            raise LayoutCompatibilityError(
                f"Slide {slide_number} selected layout {selected}, outside allowed choices {allowed}",
                slide_number=slide_number,
            )
    return structure


async def generate_presentation_structure(
    presentation_outline: PresentationOutlineModel,
    presentation_layout: PresentationLayoutModel,
    instructions: Optional[str] = None,
    using_slides_markdown: bool = False,
    source_content: Optional[str] = None,
    disconnect_checker: Optional[DisconnectChecker] = None,
    allowed_layout_indices: Optional[list[list[int]]] = None,
) -> PresentationStructureModel:
    if allowed_layout_indices is None:
        allowed_layout_indices = get_allowed_layout_indices_for_outline(
            presentation_outline,
            presentation_layout,
        )
    allowed_layout_indices = _normalize_allowed_layout_indices(
        allowed_layout_indices,
        slide_count=len(presentation_outline.slides),
        layout_count=len(presentation_layout.slides),
    )

    # If metadata narrows every slide to exactly one audited layout, there is no
    # useful choice left for an LLM to make. Returning the deterministic structure
    # saves a paid call and removes the last chance of violating the hard contract.
    if allowed_layout_indices is not None and all(
        len(indices) == 1 for indices in allowed_layout_indices
    ):
        return PresentationStructureModel(
            slides=[indices[0] for indices in allowed_layout_indices]
        )

    client = get_client(config=get_llm_config())
    model = get_model()
    response_model = get_presentation_structure_model_with_n_slides(
        len(presentation_outline.slides)
    )

    try:
        messages = (
            get_messages_for_slides_markdown(
                presentation_layout,
                len(presentation_outline.slides),
                presentation_outline.to_string(),
                instructions,
                source_content,
                allowed_layout_indices,
            )
            if using_slides_markdown
            else get_messages(
                presentation_layout,
                len(presentation_outline.slides),
                presentation_outline.to_string(),
                instructions,
                source_content,
                allowed_layout_indices,
            )
        )
        structure_schema = prepare_schema_for_validation(
            response_model.model_json_schema(),
            strict=False,
        )
        response_format = JSONSchemaResponse(
            name="response",
            json_schema=structure_schema,
            strict=False,
        )

        content = await generate_structured_with_schema_retries(
            client,
            model,
            messages=messages,
            response_format=response_format,
            json_schema=structure_schema,
            strict=False,
            validate_schema=True,
            disconnect_checker=disconnect_checker,
        )
        structure = PresentationStructureModel(**content)
    except Exception as e:
        raise handle_llm_client_exceptions(e)

    return _validate_structure_against_allowed_layouts(
        structure,
        allowed_layout_indices,
    )
