#!/usr/bin/env python3
"""Upload a PPTX and initialize a raw Template V2 candidate without a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", default="Curated template candidate")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    pptx = args.pptx.resolve()
    if not pptx.is_file():
        raise SystemExit(f"PPTX not found: {pptx}")

    base_url = args.base_url.rstrip("/")
    with pptx.open("rb") as stream:
        upload = requests.post(
            f"{base_url}/api/v1/ppt/template/fonts-upload-and-slides-preview",
            files={
                "pptx_file": (
                    pptx.name,
                    stream,
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            },
            timeout=300,
        )
    upload.raise_for_status()
    preview = upload.json()

    initialized = requests.post(
        f"{base_url}/api/v1/ppt/template/init",
        json={
            "pptx_url": preview["pptx_url"],
            "slide_image_urls": preview["slide_image_urls"],
            "fonts": preview.get("fonts") or {},
            "name": args.name,
            "description": args.description,
        },
        timeout=300,
    )
    initialized.raise_for_status()
    result = {
        "templateId": initialized.json(),
        "sourcePptx": str(pptx),
        "preview": preview,
        "modelCalls": 0,
    }
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
