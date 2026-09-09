"""Code-owned preschool compositions; never derived from business slide packs.

Each editable field has a stable teaching role. The content mapper binds by that
role, not by traversal order or which empty text box happens to fit next.
"""
from templates.ai_visual_default import _component, _text, PLACEHOLDER_IMAGE

CLASSROOM_TEMPLATE_ID = "kindergarten-classroom"
CLASSROOM_LAYOUT_PREFIX = "classroom_"


def _label(name, x, y, width, height, size=32, *, color="#203C35"):
    text = _text(name, width, height, size, 160, color=color, align="left")
    text["position"] = {"x": x, "y": y}
    text["font"]["line_height"] = 1.25
    if name == "cue":
        text["min_length"] = 0
    return text


def _picture(name, x, y, width, height):
    return {
        "type": "image", "position": {"x": x, "y": y},
        "size": {"width": width, "height": height},
        "data": PLACEHOLDER_IMAGE, "fit": "contain", "name": name,
        "decorative": False, "is_icon": False, "asset_role": "framed-image",
        "asset_mode": "composite-image", "required": True,
    }


def _base():
    return [_component("paper", "温暖奶油白的全屏课堂背景画布", [{
        "type": "vector", "shape": "polygon", "closed": True,
        "points": [{"x": 0, "y": 0}, {"x": 1280, "y": 0},
                   {"x": 1280, "y": 720}, {"x": 0, "y": 720}],
        "fill": {"color": "#FFF9EF", "opacity": 1},
    }]), _component("heading", "唯一的课堂标题，不得放入正文或步骤", [
        _label("title", 48, 24, 1184, 132, 48),
    ]), _component("invitation", "儿童操作短句；详细操作只进教师备注", [
        _label("cue", 48, 632, 1184, 72, 32, color="#79512D"),
    ])]


def classroom_layouts():
    title = _label("title", 140, 190, 1000, 110, 58)
    title["alignment"]["horizontal"] = "center"
    purpose = _label("text", 230, 350, 820, 100, 26, color="#51636F")
    purpose["alignment"]["horizontal"] = "center"
    context_label = _label("text", 440, 520, 400, 54, 24, color="#79512D")
    context_label["alignment"]["horizontal"] = "center"
    layouts = [{
        "id": "classroom_cover",
        "description": "幼教主题封面，仅呈现活动主题、活动目标与集体教学类型。",
        "components": [
            _component("paper", "稳定的奶油白封面底图与柔和装饰色块", [
                {
                    "type": "vector", "shape": "polygon", "closed": True,
                    "points": [{"x": 0, "y": 0}, {"x": 1280, "y": 0},
                               {"x": 1280, "y": 720}, {"x": 0, "y": 720}],
                    "fill": {"color": "#FFF9EF", "opacity": 1},
                },
                {
                    "type": "vector", "shape": "polygon", "closed": True,
                    "points": [{"x": 0, "y": 0}, {"x": 330, "y": 0},
                               {"x": 170, "y": 160}, {"x": 0, "y": 210}],
                    "fill": {"color": "#DDF1E7", "opacity": 1},
                },
                {
                    "type": "vector", "shape": "polygon", "closed": True,
                    "points": [{"x": 1280, "y": 720}, {"x": 930, "y": 720},
                               {"x": 1080, "y": 565}, {"x": 1280, "y": 520}],
                    "fill": {"color": "#F7D9A8", "opacity": 1},
                },
                {
                    "type": "vector", "shape": "polygon", "closed": True,
                    "points": [{"x": 510, "y": 325}, {"x": 770, "y": 325},
                               {"x": 770, "y": 329}, {"x": 510, "y": 329}],
                    "fill": {"color": "#9BCDB8", "opacity": 1},
                },
            ]),
            _component("heading", "封面中央呈现唯一醒目的活动主题主标题", [title]),
            _component("point_0", "主标题下方简洁呈现本次课堂活动目标", [purpose]),
            _component("point_1", "封面底部标明幼儿园集体教学使用类型", [context_label]),
        ],
    }]
    # No empty repeating cards. Geometry is sized for the actual number of points.
    for count in range(7):
        for side in ("left", "right"):
            components = _base()
            image_x, text_x = (48, 860) if side == "left" else (480, 48)
            image_width = 772 if count else 1184
            if not count:
                image_x = 48
            components.append(_component("scene", "突出本页教学主体的完整绘本场景", [
                _picture("visual", image_x, 174, image_width, 430),
            ]))
            height = 420 / max(count, 1)
            for index in range(count):
                components.append(_component(f"point_{index}", "保持原文与顺序的独立屏幕短句", [
                    _label("text", text_x, 174 + index * height, 372, height - 8),
                ]))
            layouts.append({
                "id": f"classroom_scene_{side}_{count}",
                "description": f"绘本大场景与{count}条独立观察/动作短句，图片占主要空间。",
                "components": components,
            })
    for count in (2, 3, 4):
        components = _base()
        width = (1184 - 28 * (count - 1)) / count
        for index in range(count):
            x = 48 + index * (width + 28)
            components.append(_component(f"card_{index}", "图片与原文成对绑定的教学卡", [
                _picture("visual", x, 170, width, 296),
                _label("text", x, 482, width, 132),
            ]))
        layouts.append({
            "id": f"classroom_cards_{count}",
            "description": f"{count}个明确图文绑定的比较、顺序或回顾单元；无空标题栏。",
            "components": components,
        })
    return layouts


def build_classroom_template():
    from models.sql.template_v2 import TemplateV2
    from templates.v2.models.layouts import SlideLayouts

    layouts = SlideLayouts.model_validate({"layouts": classroom_layouts()}).model_dump(
        mode="json", by_alias=True, exclude_none=True,
    )
    return TemplateV2(
        id=CLASSROOM_TEMPLATE_ID, name="幼教课堂 · 绘本与观察",
        description="大场景、观察短句及语义绑定图卡；教师讲稿独立保留。候选版本，待课堂成品验收。",
        layouts=layouts, is_default=True,
        assets={"template_id": CLASSROOM_TEMPLATE_ID, "images": [], "fonts": {},
                "template_metadata": {"audiences": ["child"], "allow_charts": False,
                                      "auto_match": True, "quality_status": "candidate"}},
    )
