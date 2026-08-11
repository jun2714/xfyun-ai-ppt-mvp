import sys
import asyncio

import pytest
from PIL import Image, ImageDraw, ImageFont

from services.local_ocr_service import ImageTextDetectedError, LocalOcrService


pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows.Media.Ocr integration test"
)


def test_windows_ocr_rejects_visible_english_text(tmp_path):
    image = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 90), "WATER DISPERSAL", fill="black", font=ImageFont.load_default(size=48))
    path = tmp_path / "text.png"
    image.save(path)

    with pytest.raises(ImageTextDetectedError):
        asyncio.run(LocalOcrService().reject_visible_text(str(path)))


def test_windows_ocr_accepts_text_free_shape(tmp_path):
    image = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((170, 80, 430, 340), fill=(220, 80, 60))
    path = tmp_path / "shape.png"
    image.save(path)

    asyncio.run(LocalOcrService().reject_visible_text(str(path)))
