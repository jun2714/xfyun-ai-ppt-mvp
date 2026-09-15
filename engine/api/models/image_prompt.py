from typing import Literal, Optional

from pydantic import BaseModel, Field


NO_EMBEDDED_TEXT_INSTRUCTION = (
    "画面中不要出现任何可见文字、字母、数字、标签、说明文字、答案、"
    "Logo、水印、签名或伪文字。"
)

NO_LATIN_TEXT_INSTRUCTION = (
    "画面中禁止出现任何英文、拉丁字母、英文单词、英文缩写或拼音；"
    "不要画流程图、循环图、对照表上的英文标签。"
)

CHINESE_ONLY_VISIBLE_TEXT_INSTRUCTION = (
    "画面中如需文字，只能使用简体中文；禁止英文、拉丁字母、英文单词或拼音。"
)

CHINESE_PEOPLE_INSTRUCTION = (
    "若画面出现人物，必须全部为中国人面孔与形象，符合中国幼教场景；"
    "不要出现欧美面孔。"
)

ImageAspectRatio = Literal["16:9", "4:3", "3:2", "1:1", "3:4", "2:3", "9:16"]
ImageOutputSize = Literal["0.5K", "1K", "2K", "4K"]


class ImagePrompt(BaseModel):
    prompt: str
    theme_prompt: Optional[str] = None
    prompt_language: str = Field(default="zh-CN")
    visible_language: str = Field(default="auto")
    allow_embedded_text: bool = Field(default=False)
    forbid_latin_text: bool = Field(default=True)
    ocr_policy: Literal["reject-on-detection", "disabled"] = Field(
        default="reject-on-detection"
    )
    # Provider hints. Gemini-native image models can honor these exactly; providers
    # without explicit support simply continue using their existing defaults.
    aspect_ratio: Optional[ImageAspectRatio] = None
    image_size: Optional[ImageOutputSize] = None

    def get_image_prompt(self, with_theme: bool = False) -> str:
        parts = [self.prompt.strip()]
        if with_theme and self.theme_prompt and self.theme_prompt.strip():
            parts.append(self.theme_prompt.strip())
        # The provider boundary enforces this rule so every caller receives the
        # same protection, including editor regeneration and future asset plans.
        if not self.allow_embedded_text:
            parts.append(NO_EMBEDDED_TEXT_INSTRUCTION)
        if self.forbid_latin_text:
            parts.append(
                CHINESE_ONLY_VISIBLE_TEXT_INSTRUCTION
                if self.allow_embedded_text
                else NO_LATIN_TEXT_INSTRUCTION
            )
        parts.append(CHINESE_PEOPLE_INSTRUCTION)
        return "。".join(part for part in parts if part)
