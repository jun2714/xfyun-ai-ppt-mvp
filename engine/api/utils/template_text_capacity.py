"""Conservative fixed-box checks for teacher-reviewed, non-rewritable copy."""

import math


def estimated_text_height(text: str, width: float, font_size: float,
                          line_height: float, letter_spacing: float = 0.0) -> float:
    lines = 0
    for line in (text.splitlines() or [text]):
        pixels = sum(font_size * (1.0 if ord(char) > 0x2FF else 0.55) for char in line)
        pixels += max(0, len(line) - 1) * max(letter_spacing, 0.0)
        lines += max(1, math.ceil(pixels / width))
    return lines * font_size * max(line_height, 1.0)


def template_text_boxes(element: dict) -> list[dict] | None:
    size = element.get("size") if isinstance(element.get("size"), dict) else {}
    font = element.get("font") if isinstance(element.get("font"), dict) else {}
    width, height, font_size = size.get("width"), size.get("height"), font.get("size")
    if not all(isinstance(value, (int, float)) and math.isfinite(value) and value > 0
               for value in (width, height, font_size)):
        return None
    line_height = font.get("line_height", 1.15)
    if not isinstance(line_height, (int, float)) or not math.isfinite(line_height) or line_height <= 0:
        line_height = 1.15
    spacing = font.get("letter_spacing", 0)
    if not isinstance(spacing, (int, float)) or not math.isfinite(spacing):
        spacing = 0
    return [{
        "width": float(width), "height": float(height),
        # Match the existing fitter's floor; do not introduce smaller type to
        # squeeze a long phrase into a badge or single-line caption.
        "minimum_font_size": min(float(font_size), 14.0),
        "line_height": max(float(line_height), 1.15),
        "letter_spacing": max(float(spacing), 0.0),
    }]


def locked_text_fits_field(text: str, schema: dict) -> bool:
    maximum = schema.get("maxLength")
    if isinstance(maximum, (int, float)) and len(text) > maximum:
        return False
    for box in schema.get("x-text-boxes") or []:
        required = estimated_text_height(text, box["width"], box["minimum_font_size"],
                                         box["line_height"], box.get("letter_spacing", 0))
        if required > box["height"] * 0.94:
            return False
    return True
