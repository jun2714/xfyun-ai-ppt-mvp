from models.image_prompt import (
    CHINESE_PEOPLE_INSTRUCTION,
    ImagePrompt,
    NO_EMBEDDED_TEXT_INSTRUCTION,
    NO_LATIN_TEXT_INSTRUCTION,
)
from services.research_ppt_generation_context import looks_like_english_teaching_request
from utils.llm_calls.generate_presentation_outlines import get_system_prompt
from utils.llm_calls.generate_slide_content import get_user_prompt


def test_generated_image_prompt_forbids_embedded_text_by_default():
    prompt = ImagePrompt(prompt="中国幼儿园里，孩子观察蝴蝶")

    provider_prompt = prompt.get_image_prompt()

    assert NO_EMBEDDED_TEXT_INSTRUCTION in provider_prompt
    assert NO_LATIN_TEXT_INSTRUCTION in provider_prompt
    assert CHINESE_PEOPLE_INSTRUCTION in provider_prompt
    assert prompt.allow_embedded_text is False
    assert prompt.ocr_policy == "reject-on-detection"
    assert prompt.prompt_language == "zh-CN"


def test_embedded_text_can_only_be_enabled_explicitly():
    prompt = ImagePrompt(
        prompt="用户提供的真实店招照片",
        allow_embedded_text=True,
    )

    provider_prompt = prompt.get_image_prompt()
    assert prompt.prompt in provider_prompt
    assert NO_EMBEDDED_TEXT_INSTRUCTION not in provider_prompt
    assert CHINESE_PEOPLE_INSTRUCTION in provider_prompt


def test_slide_content_prompt_separates_visible_language_from_image_prompt():
    prompt = get_user_prompt("## 蝴蝶的一生", "zh-CN")

    assert "Image Prompt Contract" in prompt
    assert "Write image_prompt fields in Chinese" in prompt
    assert "must all be Chinese people" in prompt
    assert "# Slide Language:\nzh-CN" in prompt
    assert "never ask the picture to contain English words" in prompt


def test_english_teaching_topics_are_detected():
    assert looks_like_english_teaching_request("中班英语绘本教学")
    assert looks_like_english_teaching_request("自然拼读入门")
    assert not looks_like_english_teaching_request("游戏化教学在中班语言领域的应用")


def test_outline_prompt_does_not_invent_presenter_information():
    prompt = get_system_prompt(include_title_slide=True)

    assert "only when the user supplied those facts" in prompt
    assert "Include presenter name in first slide" not in prompt
