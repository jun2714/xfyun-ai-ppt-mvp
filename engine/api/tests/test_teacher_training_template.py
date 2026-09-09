import copy

import jsonschema
import pytest

from api.v1.ppt.endpoints.presentation import (
    _apply_template_content_to_ui, _collect_non_decorative_text_elements,
    _template_text_required_height,
)
from models.presentation_outline_model import SlideContentContract, SlideOutlineModel
from services.classroom_content_mapping import build_classroom_content
from templates.teacher_training import build_training_template
from templates.v2.schema import get_template_schema


@pytest.mark.parametrize("count", range(1, 7))
def test_teacher_evidence_layout_preserves_copy_at_projectable_size(count):
    template = build_training_template()
    entries = get_template_schema(template.layouts)["layouts"]
    layout_id = f"classroom_training_scene_left_{count}"
    schema = next(entry["schema"] for entry in entries if entry["layout_id"] == layout_id)
    points = [f"观察证据{index + 1}：记录孩子原话和具体动作，再讨论支持策略。" for index in range(count)]
    title = "把主观评价改为可观察的游戏证据"
    cue = "两人一组：把一条主观判断改写成观察记录。"
    outline = SlideOutlineModel(
        content="\n".join([title, *points, cue]),
        content_contract=SlideContentContract(
            preserve_visible_copy=True, screen_title=title, screen_points=points,
            screen_instruction=cue, teacher_note="保留儿童原话，讨论可验证的支持行动。",
        ),
    )
    result = build_classroom_content(schema, outline)
    jsonschema.validate({k: v for k, v in result.items() if not k.startswith("__")}, schema)
    assert [result[f"point_{index}"]["text"] for index in range(count)] == points
    assert "专业清晰的教育编辑插画" in result["scene"]["visual"]["image_prompt"]
    assert "统一二维儿童绘本" not in result["scene"]["visual"]["image_prompt"]
    layout = next(layout for layout in template.layouts["layouts"] if layout["id"] == layout_id)
    ui = _apply_template_content_to_ui(copy.deepcopy(layout), result)
    boxes = _collect_non_decorative_text_elements(ui["components"])
    for box in boxes:
        assert box["font"]["size"] >= 32
        assert _template_text_required_height(box) <= box["size"]["height"] + 1
        assert box["position"]["x"] + box["size"]["width"] <= 1280
        assert box["position"]["y"] + box["size"]["height"] <= 720
    for index, box in enumerate(boxes):
        for other in boxes[index + 1:]:
            a, b = box["position"], other["position"]
            assert (a["x"] + box["size"]["width"] <= b["x"] or
                    b["x"] + other["size"]["width"] <= a["x"] or
                    a["y"] + box["size"]["height"] <= b["y"] or
                    b["y"] + other["size"]["height"] <= a["y"])
