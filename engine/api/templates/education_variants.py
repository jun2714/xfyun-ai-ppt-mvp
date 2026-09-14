"""Editable education packs sharing the verified semantic field contract."""
from templates.kindergarten_classroom import build_classroom_template
from templates.teacher_training import build_training_template
from templates.v2.models.layouts import SlideLayouts


EDUCATION_VARIANTS = {
    "classroom-nature": {
        "name": "自然观察 · 探索与发现", "audience": "child", "accent": "#347657",
        "background": "#F6F8EF", "ink": "#233F32", "soft": "#E1EAD5",
        "description": "适合科学探索、植物生长和天气观察；大场景配观察短句，草木绿与浅米色。",
    },
    "classroom-story": {
        "name": "故事表达 · 阅读与分享", "audience": "child", "accent": "#B6573F",
        "background": "#FFF8EE", "ink": "#593C31", "soft": "#F5DFC4",
        "description": "适合绘本讲述、语言表达和情绪主题；上方故事画面、下方短句，暖杏与珊瑚色。",
    },
    "training-case": {
        "name": "案例研讨 · 观察与证据", "audience": "teacher", "accent": "#356880",
        "background": "#F4F7F9", "ink": "#263E4C", "soft": "#DFEAF0",
        "description": "适合观察记录、案例对照和教师讨论；左侧现场配图、右侧证据正文，灰白与雾蓝。",
    },
    "training-action": {
        "name": "行动复盘 · 实施与改进", "audience": "teacher", "accent": "#846329",
        "background": "#FAF8F1", "ink": "#443D2C", "soft": "#EEE6D1",
        "description": "适合改进步骤、实施计划和教研复盘；分行行动要点与辅助配图，米白与橄榄金。",
    },
}


def semantic_template_audience(template_id):
    if template_id == "kindergarten-classroom":
        return "child"
    if template_id == "teacher-training":
        return "teacher"
    return EDUCATION_VARIANTS.get(template_id, {}).get("audience")


def _rect(name, x, y, width, height, color):
    return {
        "type": "vector", "name": name, "shape": "polygon", "closed": True,
        "decorative": True,
        "points": [{"x": x, "y": y}, {"x": x + width, "y": y},
                   {"x": x + width, "y": y + height}, {"x": x, "y": y + height}],
        "fill": {"color": color, "opacity": 1},
    }


def _place(element, x, y, width, height):
    element["position"] = {"x": x, "y": y}
    element["size"] = {"width": width, "height": height}


def build_education_variant(template_id):
    spec = EDUCATION_VARIANTS[template_id]
    teacher = spec["audience"] == "teacher"
    template = build_training_template() if teacher else build_classroom_template()
    template.id, template.name, template.description = template_id, spec["name"], spec["description"]
    palette = {
        "#FFF9EF": spec["background"], "#F5F8FA": spec["background"],
        "#203C35": spec["ink"], "#243D50": spec["ink"], "#51636F": spec["ink"],
        "#79512D": spec["accent"], "#426C78": spec["accent"],
        "#DDF1E7": spec["soft"], "#DCECF0": spec["soft"],
        "#F7D9A8": spec["soft"], "#DCE4F3": spec["soft"], "#9BCDB8": spec["accent"],
    }

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
        recolor(layout)
        layout["description"] = spec["name"] + "：" + layout["description"]
        components = {component["id"]: component for component in layout["components"]}
        paper = components["paper"]["elements"]
        # Native vectors stay behind editable copy and illustration slots.
        paper[:] = [_rect("paper", 0, 0, 1280, 720, spec["background"])]
        if layout["id"].endswith("_cover"):
            title = components["heading"]["elements"][0]
            title["font"]["size"] = 52
            title["alignment"]["horizontal"] = "center" if template_id == "classroom-story" else "left"
            _place(title, 80, 150, 1120, 150)
            for key, y, height in (("point_0", 350, 144), ("point_1", 530, 64)):
                label = components[key]["elements"][0]
                _place(label, 80, y, 1120, height)
                label["alignment"]["horizontal"] = title["alignment"]["horizontal"]
            if template_id == "classroom-story":
                paper.extend([_rect("story-top", 0, 0, 1280, 90, spec["soft"]),
                              _rect("story-bottom", 0, 630, 1280, 90, spec["soft"])])
            elif template_id == "training-case":
                paper.extend([_rect("case-spine", 0, 0, 24, 720, spec["accent"]),
                              _rect("case-rule", 80, 315, 1120, 4, spec["accent"])])
            elif template_id == "training-action":
                paper.extend([_rect("action-top", 0, 0, 1280, 20, spec["accent"]),
                              _rect("action-footer", 80, 620, 1120, 36, spec["soft"])])
            else:
                paper.extend([_rect("nature-spine", 0, 0, 24, 720, spec["accent"]),
                              _rect("nature-bottom", 0, 640, 1280, 80, spec["soft"])])
            continue

        paper.append(_rect("heading-rule", 48, 157, 1184, 4, spec["accent"]))
        if template_id == "training-case":
            paper.append(_rect("heading-wash", 0, 0, 1280, 157, spec["soft"]))
        if "_cards_" in layout["id"]:
            # Keep the exact image/caption field pairs and generous teacher captions.
            for key, component in components.items():
                if key.startswith("card_"):
                    box = component["elements"][0]
                    x, width = box["position"]["x"], box["size"]["width"]
                    paper.append(_rect(key + "-rule", x, 614, width, 4, spec["accent"]))
            continue

        count = int(layout["id"].rsplit("_", 1)[-1])
        scene = components["scene"]["elements"][0]
        if not count:
            _place(scene, 48, 174, 1184, 430)
            continue
        if template_id == "classroom-story":
            _place(scene, 48, 174, 1184, 220 if count > 3 else 248)
        elif template_id == "classroom-nature":
            _place(scene, 48, 174, 680 if count <= 3 else 500, 430)
        elif template_id == "training-case":
            _place(scene, 48, 174, 324, 430)
        else:
            _place(scene, 908, 174, 324, 430)

        for index in range(count):
            text = components[f"point_{index}"]["elements"][0]
            text["alignment"]["vertical"] = "top"
            if template_id == "classroom-story":
                cols = min(count, 3)
                rows = (count + cols - 1) // cols
                width = (1184 - (cols - 1) * 28) / cols
                row, col = divmod(index, cols)
                _place(text, 48 + col * (width + 28),
                       414 + row * 104 if rows == 2 else 442,
                       width, 96 if rows == 2 else 172)
            elif template_id == "classroom-nature":
                rows = count if count <= 3 else (count + 1) // 2
                col, row = (0, index) if count <= 3 else divmod(index, rows)
                _place(text, (780 if count <= 3 else 584) + col * 338,
                       174 + row * 430 / rows, 452 if count <= 3 else 310, 430 / rows - 12)
            else:
                rows = count if count <= 3 else (count + 1) // 2
                col, row = (0, index) if count <= 3 else divmod(index, rows)
                x = (420 if template_id == "training-case" else 76) + col * 420
                _place(text, x, 174 + row * 430 / rows,
                       (812 if count <= 3 else 392) - (28 if template_id == "training-action" else 0),
                       430 / rows - 12)
                if template_id == "training-action":
                    paper.append(_rect(f"step-{index}", x - 28, 174 + row * 430 / rows,
                                       5, 430 / rows - 20, spec["accent"]))
    template.layouts = SlideLayouts.model_validate(template.layouts).model_dump(
        mode="json", by_alias=True, exclude_none=True,
    )
    template.assets = {
        "template_id": template_id, "images": [], "fonts": {},
        "thumbnail": f"/static/templates/{template_id}.svg",
        "template_metadata": {"audiences": [spec["audience"]], "allow_charts": False,
                              "auto_match": False, "quality_status": "candidate"},
    }
    return template
