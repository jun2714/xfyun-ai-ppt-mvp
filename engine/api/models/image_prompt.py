from typing import Literal, Optional

from pydantic import BaseModel, Field


NO_EMBEDDED_TEXT_INSTRUCTION = (
    "Do not include any visible text, letters, numbers, labels, captions, "
    "answers, logos, watermarks, signatures, or pseudo-text in the image."
)


class ImagePrompt(BaseModel):
    prompt: str
    theme_prompt: Optional[str] = None
    prompt_language: str = Field(default="auto")
    visible_language: str = Field(default="auto")
    allow_embedded_text: bool = Field(default=False)
    ocr_policy: Literal["reject-on-detection", "disabled"] = Field(
        default="reject-on-detection"
    )

    def get_image_prompt(self, with_theme: bool = False) -> str:
        parts = [self.prompt.strip()]
        if with_theme and self.theme_prompt and self.theme_prompt.strip():
            parts.append(self.theme_prompt.strip())
        # The provider boundary enforces this rule so every caller receives the
        # same protection, including editor regeneration and future asset plans.
        if not self.allow_embedded_text:
            parts.append(NO_EMBEDDED_TEXT_INSTRUCTION)
        return ", ".join(part for part in parts if part)
