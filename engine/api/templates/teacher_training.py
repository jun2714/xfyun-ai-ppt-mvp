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
        if "_scene_" not in layout["id"]:
            continue
        count = int(layout["id"].rsplit("_", 1)[-1])
        if count == 0:
            continue
        rows = count if count <= 3 else (count + 1) // 2
        for component in layout["components"]:
            for element in component["elements"]:
                if component["id"] == "scene":
                    element["position"] = {"x": 908, "y": 174}
                    element["size"] = {"width": 324, "height": 430}
                elif component["id"].startswith("point_"):
                    index = int(component["id"].split("_")[-1])
                    column, row = (0, index) if count <= 3 else divmod(index, rows)
                    element["position"] = {"x": 48 + column * 420, "y": 174 + row * 430 / rows}
                    element["size"] = {"width": 812 if count <= 3 else 392,
                                       "height": 430 / rows - 12}
                    element["alignment"]["vertical"] = "top"
                    element["font"]["bold"] = False
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
