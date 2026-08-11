#!/usr/bin/env python3
"""Apply a reviewed template curation manifest without calling a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-id", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    payload = {
        "templateId": args.template_id,
        "layouts": manifest["layouts"],
    }
    request = Request(
        args.base_url.rstrip("/")
        + "/api/v1/ppt/template/layouts/derive-without-model",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"template derivation failed ({exc.code}): {detail}") from exc

    print(
        json.dumps(
            {
                "templateId": result["id"],
                "name": result["name"],
                "layoutCount": result["layout_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
