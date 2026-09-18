from PIL import Image, ImageDraw

from services.sprite_sheet_service import (
    crop_sprite_sheet,
    crop_to_aspect_ratio,
    fit_to_aspect_ratio,
)


def test_crop_sprite_sheet_creates_transparent_cutouts(tmp_path):
    source = Image.new("RGB", (1024, 1024), "white")
    draw = ImageDraw.Draw(source)
    for row in range(2):
        for column in range(2):
            left = column * 512 + 110
            top = row * 512 + 90
            draw.ellipse((left, top, left + 280, top + 320), fill=(220, 80, 60))
    source_path = tmp_path / "sheet.png"
    source.save(source_path)

    outputs = crop_sprite_sheet(str(source_path), str(tmp_path / "out"), 2, 2, 4)

    assert len(outputs) == 4
    for output in outputs:
        image = Image.open(output)
        assert image.mode == "RGBA"
        assert image.getchannel("A").getextrema()[0] == 0


def test_background_is_cropped_to_requested_aspect_ratio(tmp_path):
    source = Image.new("RGB", (1024, 1024), "blue")
    source_path = tmp_path / "square.png"
    source.save(source_path)

    output = crop_to_aspect_ratio(str(source_path), str(tmp_path / "out"), "16:9")
    image = Image.open(output)

    assert abs(image.width / image.height - 16 / 9) < 0.01


def test_fit_to_aspect_ratio_pads_instead_of_cropping_heads(tmp_path):
    source = Image.new("RGB", (100, 100), "white")
    source.putpixel((50, 2), (255, 0, 0))
    source.putpixel((50, 97), (0, 0, 255))
    source_path = tmp_path / "square.png"
    source.save(source_path)

    cropped = Image.open(
        crop_to_aspect_ratio(str(source_path), str(tmp_path / "crop"), "16:9")
    )
    padded = Image.open(
        fit_to_aspect_ratio(
            str(source_path), str(tmp_path / "pad"), "16:9", crop=False
        )
    )

    assert (255, 0, 0, 255) not in set(cropped.getdata())
    assert (255, 0, 0, 255) in set(padded.getdata())
    assert (0, 0, 255, 255) in set(padded.getdata())
    assert abs(padded.width / padded.height - 16 / 9) < 0.01
