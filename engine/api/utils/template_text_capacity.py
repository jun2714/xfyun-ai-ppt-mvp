"""Conservative fixed-box checks for teacher-reviewed, non-rewritable copy."""

import math


def template_text_boxes(element: dict) -> list[dict] | None:
    size = element.get("size") or {}
    font = element.get("font") or {}
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
        "line_height": max(float(line_height), 1.0),
        "letter_spacing": max(float(spacing), 0.0),
    }]


def locked_text_fits_field(text: str, schema: dict) -> bool:
    maximum = schema.get("maxLength")
    if isinstance(maximum, (int, float)) and len(text) > maximum:
        return False
    for box in schema.get("x-text-boxes") or []:
        font_size = box["minimum_font_size"]
        width = box["width"]
        lines = 0
        for line in (text.splitlines() or [text]):
            pixels = sum(font_size * (1.0 if ord(char) > 0x2FF else 0.55) for char in line)
            pixels += max(0, len(line) - 1) * box.get("letter_spacing", 0)
            lines += max(1, math.ceil(pixels / width))
        if lines * font_size * box["line_height"] > box["height"] * 0.94:
            return False
    return True
