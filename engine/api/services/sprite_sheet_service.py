from __future__ import annotations

from collections import deque
from pathlib import Path
import uuid

from PIL import Image


def crop_sprite_sheet(
    source_path: str,
    output_directory: str,
    columns: int,
    rows: int,
    expected_count: int,
) -> list[str]:
    if columns not in {2, 3} or rows != 2:
        raise ValueError("Only audited 2x2 and 2x3 sprite grids are supported")
    if expected_count < 1 or expected_count > columns * rows:
        raise ValueError("Sprite subject count does not fit the declared grid")

    source = Image.open(source_path).convert("RGBA")
    cell_width = source.width // columns
    cell_height = source.height // rows
    if cell_width < 256 or cell_height < 256:
        raise ValueError("Sprite cells are too small for PPT display")

    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for index in range(expected_count):
        column = index % columns
        row = index // columns
        left = column * cell_width
        top = row * cell_height
        right = source.width if column == columns - 1 else left + cell_width
        bottom = source.height if row == rows - 1 else top + cell_height
        cell = source.crop((left, top, right, bottom))
        cutout = remove_edge_connected_background(cell)
        _validate_cutout(cutout)
        output = destination / f"{uuid.uuid4()}.png"
        cutout.save(output, format="PNG")
        outputs.append(str(output))
    return outputs


def create_transparent_cutout(source_path: str, output_directory: str) -> str:
    source = Image.open(source_path).convert("RGBA")
    cutout = remove_edge_connected_background(source)
    _validate_cutout(cutout)
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"{uuid.uuid4()}.png"
    cutout.save(output, format="PNG")
    return str(output)


def crop_to_aspect_ratio(
    source_path: str,
    output_directory: str,
    aspect_ratio: str,
) -> str:
    match = aspect_ratio.split(":", 1)
    if len(match) != 2:
        return source_path
    try:
        target_ratio = float(match[0]) / float(match[1])
    except (ValueError, ZeroDivisionError):
        return source_path
    source = Image.open(source_path).convert("RGBA")
    current_ratio = source.width / source.height
    if abs(current_ratio - target_ratio) < 0.01:
        return source_path
    if current_ratio > target_ratio:
        target_width = round(source.height * target_ratio)
        left = (source.width - target_width) // 2
        box = (left, 0, left + target_width, source.height)
    else:
        target_height = round(source.width / target_ratio)
        top = (source.height - target_height) // 2
        box = (0, top, source.width, top + target_height)
    cropped = source.crop(box)
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"{uuid.uuid4()}.png"
    cropped.save(output, format="PNG")
    return str(output)


def remove_edge_connected_background(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    corners = [pixels[0, 0][:3], pixels[width - 1, 0][:3], pixels[0, height - 1][:3], pixels[width - 1, height - 1][:3]]
    background = tuple(sum(color[channel] for color in corners) // 4 for channel in range(3))

    def distance(rgb) -> int:
        return max(abs(int(rgb[channel]) - background[channel]) for channel in range(3))

    queue = deque()
    visited: set[tuple[int, int]] = set()
    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))

    while queue:
        x, y = queue.popleft()
        if (x, y) in visited:
            continue
        visited.add((x, y))
        pixel = pixels[x, y]
        color_distance = distance(pixel[:3])
        if color_distance > 42:
            continue
        # A narrow soft threshold reduces visible color spill without deleting
        # similarly colored pixels enclosed inside the subject.
        alpha = 0 if color_distance <= 22 else int(255 * (color_distance - 22) / 20)
        pixels[x, y] = (*pixel[:3], min(pixel[3], alpha))
        if x > 0:
            queue.append((x - 1, y))
        if x + 1 < width:
            queue.append((x + 1, y))
        if y > 0:
            queue.append((x, y - 1))
        if y + 1 < height:
            queue.append((x, y + 1))
    return rgba


def _validate_cutout(image: Image.Image) -> None:
    alpha = image.getchannel("A")
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError("Sprite cell has no visible subject")
    if alpha.getextrema()[0] == 255:
        raise ValueError("Sprite cutout has no transparent background")
    left, top, right, bottom = bounds
    margin_x = max(2, image.width // 100)
    margin_y = max(2, image.height // 100)
    if left <= margin_x or top <= margin_y or right >= image.width - margin_x or bottom >= image.height - margin_y:
        raise ValueError("Sprite subject touches a cell edge and may be cropped")
