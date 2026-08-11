from __future__ import annotations

from pathlib import Path
import uuid

import aiohttp

from models.sql.image_asset import ImageAsset
from services.local_ocr_service import LocalOcrService


async def materialize_and_validate_no_text(
    result: str | ImageAsset,
    output_directory: str,
    ocr_service: LocalOcrService,
) -> str | ImageAsset:
    materialized = result
    if isinstance(result, str):
        if not result.startswith(("http://", "https://")):
            raise ValueError("Generated image is not available as a local file")
        destination = Path(output_directory) / f"{uuid.uuid4()}.png"
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(
                result,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response:
                if response.status != 200:
                    raise ValueError(
                        f"Unable to download generated image for OCR: {response.status}"
                    )
                destination.write_bytes(await response.read())
        materialized = ImageAsset(
            path=str(destination),
            is_uploaded=False,
            extras={"source_url": result},
        )

    await ocr_service.reject_visible_text(materialized.path)
    return materialized
