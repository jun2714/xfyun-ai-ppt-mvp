import os

from enums.image_provider import ImageProvider
from utils.get_env import (
    get_disable_image_generation_env,
    get_image_provider_env,
)
from utils.parsers import parse_bool_or_none


def is_image_generation_disabled() -> bool:
    return parse_bool_or_none(get_disable_image_generation_env()) or False


def is_pixels_selected() -> bool:
    return ImageProvider.PEXELS == get_selected_image_provider()


def is_pixabay_selected() -> bool:
    return ImageProvider.PIXABAY == get_selected_image_provider()


def is_openai_compatible_selected() -> bool:
    return ImageProvider.OPENAI_COMPATIBLE == get_selected_image_provider()


def is_gemini_flash_selected() -> bool:
    return ImageProvider.GEMINI_FLASH == get_selected_image_provider()


def is_nanobanana_pro_selected() -> bool:
    return ImageProvider.NANOBANANA_PRO == get_selected_image_provider()


def is_dalle3_selected() -> bool:
    return ImageProvider.DALLE3 == get_selected_image_provider()


def is_gpt_image_1_5_selected() -> bool:
    return ImageProvider.GPT_IMAGE_1_5 == get_selected_image_provider()


def is_comfyui_selected() -> bool:
    return ImageProvider.COMFYUI == get_selected_image_provider()


def is_open_webui_selected() -> bool:
    return ImageProvider.OPEN_WEBUI == get_selected_image_provider()


def get_selected_image_provider() -> ImageProvider | None:
    """Resolve the image provider from explicit or DMX-only configuration."""
    image_provider_env = get_image_provider_env()
    if image_provider_env:
        return ImageProvider(image_provider_env)

    dmx_style = (os.getenv("DMX_IMAGE_API_STYLE") or "").strip().casefold()
    dmx_model = (os.getenv("DMX_IMAGE_MODEL") or "").strip()
    if dmx_style == "gemini" and dmx_model:
        return ImageProvider.GEMINI_FLASH

    return None
