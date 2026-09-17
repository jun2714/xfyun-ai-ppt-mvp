"""Code-owned teacher workshop layouts with room for evidence and actions."""
import copy

from templates.kindergarten_classroom import build_classroom_template
from templates.v2.models.layouts import SlideLayouts

TRAINING_TEMPLATE_ID = "teacher-training"


def build_training_template():
    template = build_classroom_template()
    template.id = TRAINING_TEMPLATE_ID
    template.name = "园本教研 · 问题与策略"
    template.description = "面向教师培训、案例对照与改进计划；大字号正文、独立讲稿和对应配图。"
    template.layouts = copy.deepcopy(template.layouts)
    palette = {"#FFF9EF": "#F5F8FA", "#203C35": "#243D50",
               "#79512D": "#426C78", "#DDF1E7": "#DCECF0", "#F7D9A8": "#DCE4F3"}

    def recolor(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, str) and child in palette:
                    value[key] = palette[child]
                else:
                    recolor(child)
        elif isinstance(value, list):
            for child in value:
                recolor(child)

    for layout in template.layouts["layouts"]:
        layout["id"] = layout["id"].replace("classroom_", "classroom_training_", 1)
        layout["description"] = "园本教研：" + layout["description"]
        recolor(layout)
        if "_cards_" in layout["id"]:
            # Evidence captions need more room than child-facing picture labels.
            for component in layout["components"]:
                if not component["id"].startswith("card_"):
                    continue
                for element in component["elements"]:
                    if element["type"] == "image":
                        element["size"]["height"] = 208
                    elif element["type"] == "text":
                        element["position"]["y"] = 396
                        element["size"]["height"] = 218
                        element["font"]["bold"] = False
        if "_scene_" not in layout["id"]:
            continue
        for component in layout["components"]:
            if component["id"].startswith("point_"):
                component["elements"][0]["font"]["bold"] = False

    # A real third composition for teacher decks. The earlier pack exposed many
    # layout ids but collapsed both left/right scene layouts into identical
    # geometry, so a ten-page deck looked like one repeated slide.
    top_layouts = []
    for source in template.layouts["layouts"]:
        if "_scene_left_" not in source["id"]:
            continue
        count = int(source["id"].rsplit("_", 1)[-1])
        if count not in {1, 2, 3, 4}:
            continue
        layout = copy.deepcopy(source)
        layout["id"] = layout["id"].replace("_scene_left_", "_scene_top_")
        layout["description"] = "园本教研：上方完整案例场景，下方分栏呈现观察或行动要点。"
        top_layouts.append(layout)
    template.layouts["layouts"].extend(top_layouts)
    from templates.teaching_geometry import arrange_teacher_scene
    for layout in template.layouts["layouts"]:
        arrange_teacher_scene(layout)
    template.layouts = SlideLayouts.model_validate(template.layouts).model_dump(
        mode="json", by_alias=True, exclude_none=True,
    )
    template.assets = {
        "template_id": TRAINING_TEMPLATE_ID, "images": [], "fonts": {},
        "thumbnail": "/static/templates/teacher-training.svg",
        "template_metadata": {"audiences": ["teacher"], "allow_charts": False,
                              "auto_match": True, "quality_status": "candidate"},
    }
    return template
