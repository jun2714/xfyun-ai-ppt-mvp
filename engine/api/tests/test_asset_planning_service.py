from models.sql.slide import SlideModel
from services.asset_planning_service import build_asset_plan, extract_asset_slots


def _slide(index: int, images: list[dict], content: dict) -> SlideModel:
    return SlideModel(
        presentation="00000000-0000-0000-0000-000000000001",
        layout_group="test",
        layout="test",
        index=index,
        content=content,
        ui={"components": [{"id": "main", "elements": images}]},
    )


def test_full_canvas_image_is_planned_as_background_without_guessing_topic():
    slide = _slide(
        0,
        [
            {
                "type": "image",
                "name": "hero",
                "position": {"x": 0, "y": 0},
                "size": {"width": 1280, "height": 720},
                "fit": "cover",
            }
        ],
        {"main": {"hero": {"image_prompt": "A calm forest scene"}}},
    )

    slots = extract_asset_slots([slide])
    plan = build_asset_plan([slide])

    assert slots[0].role == "background"
    assert slots[0].aspect_ratio == "16:9"
    assert plan[0].generation_mode == "direct-background"


def test_identical_compatible_prompts_are_generated_once_and_reused():
    images = [
        {
            "type": "image",
            "name": "subject",
            "position": {"x": 200, "y": 100},
            "size": {"width": 400, "height": 400},
        }
    ]
    slides = [
        _slide(i, images, {"main": {"subject": {"image_prompt": "A red kite"}}})
        for i in range(2)
    ]

    plan = build_asset_plan(slides)

    assert len(plan) == 1
    assert plan[0].generation_mode == "reuse-or-search"
    assert plan[0].consumer_slot_count == 2


def test_sprite_sheet_requires_explicit_group_and_cutout_roles():
    images = []
    content = {"main": {}}
    for index in range(4):
        name = f"animal_{index}"
        images.append(
            {
                "type": "image",
                "name": name,
                "position": {"x": 100 + index * 200, "y": 200},
                "size": {"width": 180, "height": 240},
                "asset_role": "cutout",
                "asset_mode": "sprite-sheet",
                "asset_group": "subjects",
            }
        )
        content["main"][name] = {"image_prompt": f"Animal {index}"}

    plan = build_asset_plan([_slide(0, images, content)])

    assert len(plan) == 1
    assert plan[0].generation_mode == "sprite-sheet"
    assert (plan[0].grid_columns, plan[0].grid_rows) == (2, 2)
    assert plan[0].consumer_slot_count == 4
