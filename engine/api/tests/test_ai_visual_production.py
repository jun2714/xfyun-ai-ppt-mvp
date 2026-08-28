from templates.ai_visual_production import build_production_ai_visual_template


def _walk_images(value):
    found = []
    if isinstance(value, dict):
        if value.get("type") == "image":
            found.append(value)
        for child in value.values():
            found.extend(_walk_images(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_images(child))
    return found


def test_ai_visual_skeleton_has_eight_distinct_layouts():
    template = build_production_ai_visual_template()
    layouts = template.layouts["layouts"]
    ids = [layout["id"] for layout in layouts]

    assert template.id == "ai-visual"
    assert len(layouts) >= 8
    assert len(ids) == len(set(ids))
    assert "ai_compare" in ids
    assert "ai_sequence" in ids


def test_every_ai_visual_layout_has_one_full_canvas_background_slot():
    template = build_production_ai_visual_template()

    for layout in template.layouts["layouts"]:
        backgrounds = [
            image
            for image in _walk_images(layout)
            if image.get("asset_role") == "background"
        ]
        assert len(backgrounds) == 1, layout["id"]
        background = backgrounds[0]
        assert background["size"] == {"width": 1280.0, "height": 720.0}
        assert background["asset_mode"] == "direct-background"
        assert background["aspect_ratio"] == "16:9"


def test_ai_visual_template_disables_business_charts_and_keeps_projection_readability():
    template = build_production_ai_visual_template()
    metadata = template.assets["template_metadata"]

    assert metadata["allow_charts"] is False
    assert metadata["minimum_layout_count"] == 8
    for layout in template.layouts["layouts"]:
        assert layout["metadata"]["readability"]["minimumFontSize"] >= 22
        assert layout["metadata"]["qualityStatus"] == "candidate"


def test_multi_item_layout_uses_one_sprite_group_for_cutouts():
    template = build_production_ai_visual_template()
    multi = next(
        layout
        for layout in template.layouts["layouts"]
        if layout["id"] == "ai_multi_item"
    )
    cutouts = [
        image
        for image in _walk_images(multi)
        if image.get("asset_role") == "cutout"
    ]

    assert len(cutouts) == 4
    assert {image["asset_mode"] for image in cutouts} == {"sprite-sheet"}
    assert {image["asset_group"] for image in cutouts} == {"game_items"}
