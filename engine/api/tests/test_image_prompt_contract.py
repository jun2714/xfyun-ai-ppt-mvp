from models.image_prompt import ImagePrompt, NO_EMBEDDED_TEXT_INSTRUCTION
from utils.llm_calls.generate_presentation_outlines import get_system_prompt
from utils.llm_calls.generate_slide_content import get_user_prompt


def test_generated_image_prompt_forbids_embedded_text_by_default():
    prompt = ImagePrompt(prompt="A child observing a butterfly")

    provider_prompt = prompt.get_image_prompt()

    assert NO_EMBEDDED_TEXT_INSTRUCTION in provider_prompt
    assert prompt.allow_embedded_text is False
    assert prompt.ocr_policy == "reject-on-detection"


def test_embedded_text_can_only_be_enabled_explicitly():
    prompt = ImagePrompt(
        prompt="A real storefront sign supplied by the user",
        allow_embedded_text=True,
    )

    assert prompt.get_image_prompt() == prompt.prompt


def test_slide_content_prompt_separates_visible_language_from_image_prompt():
    prompt = get_user_prompt("## 蝴蝶的一生", "zh-CN")

    assert "Image Prompt Contract" in prompt
    assert "pseudo-text" in prompt
    assert "# Slide Language:\nzh-CN" in prompt


def test_outline_prompt_does_not_invent_presenter_information():
    prompt = get_system_prompt(include_title_slide=True)

    assert "only when the user supplied those facts" in prompt
    assert "Include presenter name in first slide" not in prompt
