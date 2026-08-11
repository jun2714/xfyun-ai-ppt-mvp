from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import sys


class LocalOcrUnavailableError(RuntimeError):
    pass


class ImageTextDetectedError(ValueError):
    def __init__(self, text: str):
        super().__init__(f"Generated image contains visible text: {text[:120]}")
        self.text = text


class LocalOcrService:
    def __init__(self) -> None:
        self._script = (
            Path(__file__).resolve().parents[3] / "scripts" / "windows-ocr.ps1"
        )

    async def recognize(self, image_path: str) -> str:
        if sys.platform != "win32" or not self._script.is_file():
            raise LocalOcrUnavailableError(
                "A supported local OCR engine is required before image generation can pass"
            )
        process = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self._script),
            "-ImagePath",
            str(Path(image_path).resolve()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise LocalOcrUnavailableError("Windows OCR timed out") from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise LocalOcrUnavailableError(detail or "Windows OCR failed")
        try:
            payload = json.loads(stdout.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalOcrUnavailableError("Windows OCR returned invalid JSON") from exc
        text = payload.get("text") if isinstance(payload, dict) else None
        return str(text or "").strip()

    async def reject_visible_text(self, image_path: str) -> None:
        text = await self.recognize(image_path)
        normalized = re.sub(r"\s+", "", text)
        if normalized:
            raise ImageTextDetectedError(text)
