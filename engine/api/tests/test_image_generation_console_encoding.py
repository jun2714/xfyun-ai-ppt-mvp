import asyncio
import contextlib
import io

import pytest

from models.image_prompt import ImagePrompt
from services.image_generation_service import ImageGenerationService
from utils.image_generation_error import ImageGenerationHTTPException


@pytest.mark.parametrize("provider_fails", [False, True])
def test_gbk_console_cannot_interrupt_unicode_image_requests(provider_fails):
    service = ImageGenerationService.__new__(ImageGenerationService)
    service.output_directory = "."
    service.is_image_generation_disabled = False
    service.is_stock_provider_selected = lambda: False
    seen = []

    async def provider(prompt, _directory):
        seen.append(prompt)
        if provider_fails:
            raise ValueError("图片失败 • 🌱")
        return "https://example.com/generated.png"

    service.image_gen_func = provider
    output = io.TextIOWrapper(io.BytesIO(), encoding="gbk", errors="strict")
    with contextlib.redirect_stdout(output):
        request = service.generate_image(ImagePrompt(prompt="小种子 • 🌱"))
        if provider_fails:
            with pytest.raises(ImageGenerationHTTPException) as caught:
                asyncio.run(request)
            assert isinstance(caught.value.__cause__, ValueError)
            assert str(caught.value.__cause__) == "图片失败 • 🌱"
        else:
            assert asyncio.run(request) == "https://example.com/generated.png"
    assert len(seen) == 1
    assert "小种子 • 🌱" in seen[0]
