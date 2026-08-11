import json
import re
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "usage: validate-pptx.py <file> <expected-slide-count> "
            "[--strict-exit] [--require-wps-render]",
            file=sys.stderr,
        )
        return 64

    file = Path(sys.argv[1])
    expected = int(sys.argv[2])
    strict_exit = "--strict-exit" in sys.argv[3:]
    require_wps_render = "--require-wps-render" in sys.argv[3:]
    issues: list[dict[str, object]] = []
    slides: list[str] = []
    placeholder = re.compile(
        r"(?:lorem ipsum|title here|heading|enter text|image prompt|negative prompt|"
        r"图片描述|生图提示词|负面提示词|设计意图|制作说明)",
        re.I,
    )

    try:
        with zipfile.ZipFile(file) as archive:
            names = archive.namelist()
            slides = sorted(
                (
                    name
                    for name in names
                    if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
                ),
                key=lambda name: int(re.search(r"\d+", name).group()),
            )
            if len(slides) != expected:
                issues.append(
                    {
                        "code": "SLIDE_COUNT_MISMATCH",
                        "message": f"expected {expected}, received {len(slides)}",
                    }
                )

            for index, name in enumerate(slides, 1):
                root = ET.fromstring(archive.read(name))
                text = " ".join(
                    (node.text or "")
                    for node in root.iter()
                    if node.tag.endswith("}t")
                )
                if not text.strip():
                    issues.append(
                        {
                            "code": "EMPTY_SLIDE",
                            "message": "slide has no editable visible text",
                            "slideNumber": index,
                        }
                    )
                if placeholder.search(text):
                    issues.append(
                        {
                            "code": "PLACEHOLDER_COPY",
                            "message": "template or production copy is visible",
                            "slideNumber": index,
                        }
                    )

                for shape in root.iter():
                    if not shape.tag.endswith("}sp"):
                        continue
                    has_placeholder = any(
                        child.tag.endswith("}ph") for child in shape.iter()
                    )
                    has_text = any(
                        (child.text or "").strip()
                        for child in shape.iter()
                        if child.tag.endswith("}t")
                    )
                    if has_placeholder and not has_text:
                        issues.append(
                            {
                                "code": "EMPTY_PLACEHOLDER",
                                "message": "empty structural placeholder",
                                "slideNumber": index,
                            }
                        )

            required = {"[Content_Types].xml", "ppt/presentation.xml"}
            for name in required - set(names):
                issues.append(
                    {"code": "OOXML_PART_MISSING", "message": f"missing {name}"}
                )
    except (zipfile.BadZipFile, ET.ParseError, OSError, ValueError) as error:
        issues.append({"code": "PPTX_INVALID", "message": str(error)})

    wps_render: dict[str, object] | None = None
    if require_wps_render and not any(
        issue["code"] in {"PPTX_INVALID", "SLIDE_COUNT_MISMATCH"}
        for issue in issues
    ):
        wps_render = render_with_wps(file, expected, issues)

    report = {
        "passed": not issues,
        "slideCount": len(slides),
        "issues": issues,
        "wpsRender": wps_render,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 2 if strict_exit and issues else 0


def render_with_wps(
    file: Path,
    expected: int,
    issues: list[dict[str, object]],
) -> dict[str, object]:
    if sys.platform != "win32":
        issues.append(
            {
                "code": "WPS_RENDER_UNAVAILABLE",
                "message": "WPS rendering is required on the validation host",
            }
        )
        return {"passed": False, "slideCount": 0}

    renderer = Path(__file__).with_name("render-pptx-wps.ps1")
    with tempfile.TemporaryDirectory(prefix="sparkdeck-wps-") as directory:
        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(renderer),
                    "-InputFile",
                    str(file.resolve()),
                    "-OutputDirectory",
                    directory,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            rendered = sorted(Path(directory).glob("slide-*.png"))
            if len(rendered) != expected:
                issues.append(
                    {
                        "code": "WPS_RENDER_COUNT_MISMATCH",
                        "message": f"WPS rendered {len(rendered)} of {expected} slides",
                    }
                )
            invalid_dimensions = [
                image.name for image in rendered if png_dimensions(image) != (1280, 720)
            ]
            if invalid_dimensions:
                issues.append(
                    {
                        "code": "WPS_RENDER_DIMENSIONS_INVALID",
                        "message": "unexpected PNG dimensions: "
                        + ", ".join(invalid_dimensions),
                    }
                )
            return {
                "passed": len(rendered) == expected and not invalid_dimensions,
                "slideCount": len(rendered),
                "rendererOutput": completed.stdout.strip(),
            }
        except (OSError, subprocess.SubprocessError) as error:
            issues.append(
                {"code": "WPS_RENDER_FAILED", "message": str(error)}
            )
            return {"passed": False, "slideCount": 0}


def png_dimensions(file: Path) -> tuple[int, int] | None:
    try:
        with file.open("rb") as stream:
            if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                return None
            length = struct.unpack(">I", stream.read(4))[0]
            if stream.read(4) != b"IHDR" or length < 8:
                return None
            return struct.unpack(">II", stream.read(8))
    except (OSError, struct.error):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
