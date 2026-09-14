"""Editable education packs sharing the verified semantic field contract."""
import copy

from templates.kindergarten_classroom import build_classroom_template, _label
from templates.teacher_training import build_training_template
from templates.v2.models.layouts import SlideLayouts


EDUCATION_VARIANTS = {
    "classroom-nature": {
        "name": "自然观察 · 探索与发现", "audience": "child", "accent": "#347657",
        "background": "#F6F8EF", "ink": "#233F32", "soft": "#E1EAD5",
        "description": "观察手册风格：草木绿书脊、标本画框与观察记录，适合科学探索、植物和天气。",
    },
    "classroom-story": {
        "name": "故事表达 · 阅读与分享", "audience": "child", "accent": "#245B59",
        "background": "#FFF6E5", "ink": "#244747", "soft": "#F5C85C",
        "description": "绘本分镜风格：明黄与深青、分镜边框和故事短句，适合阅读讲述与情绪表达。",
    },
    "training-case": {
        "name": "案例研讨 · 观察与证据", "audience": "teacher", "accent": "#233C57",
        "background": "#F4F7F9", "ink": "#263E4C", "soft": "#DFEAF0",
        "description": "案例档案风格：深蓝标题栏、白色证据卡与对照网格，适合观察记录和案例研讨。",
    },
    "training-action": {
        "name": "行动复盘 · 实施与改进", "audience": "teacher", "accent": "#A84D32",
        "background": "#FBF5EF", "ink": "#50372D", "soft": "#F3DBCB",
        "description": "步骤路线图风格：陶土红编号、行动轨道与结果配图，适合实施计划和教研复盘。",
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


def _number(value, x, y, color):
    label = _label("ordinal", x, y, 48, 48, 32, color=color)
    label["runs"] = [{"text": f"{value:02d}"}]
    label["decorative"] = True
    return label


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

    # Roomier alternatives preserve all field names, point counts and image pairs.
    # A fallback can change geometry, never the reviewed lesson itself.
    extra = []
    for layout in template.layouts["layouts"]:
        if "_scene_left_" in layout["id"] and not layout["id"].endswith("_0"):
            roomy = copy.deepcopy(layout)
            roomy["id"] = roomy["id"].replace("_scene_left_", "_scene_roomy_")
            extra.append(roomy)
        elif "_cards_" in layout["id"]:
            roomy = copy.deepcopy(layout)
            roomy["id"] = roomy["id"].replace("_cards_", "_cards_roomy_")
            extra.append(roomy)
    template.layouts["layouts"].extend(extra)

    for layout in template.layouts["layouts"]:
        recolor(layout)
        roomy = "_roomy_" in layout["id"]
        layout["description"] = spec["description"] + (" 正文扩展版。" if roomy else " 标准版。")
        components = {component["id"]: component for component in layout["components"]}
        paper = components["paper"]["elements"]
        paper[:] = [_rect("paper", 0, 0, 1280, 720, spec["background"])]
        title = components["heading"]["elements"][0]
        if layout["id"].endswith("_cover"):
            # Four different cover compositions, retaining exactly title/goal/usage.
            title["font"]["size"] = 52
            _place(title, 80, 120, 1120, 150)
            _place(components["point_0"]["elements"][0], 80, 350, 1120, 144)
            _place(components["point_1"]["elements"][0], 80, 530, 1120, 64)
            for key in ("heading", "point_0", "point_1"):
                components[key]["elements"][0]["alignment"]["horizontal"] = "left"
            if template_id == "classroom-nature":
                paper.extend([_rect("spine", 0, 0, 30, 720, spec["accent"]),
                              _rect("page", 56, 48, 1184, 624, "#FFFFFF"),
                              _rect("tab", 80, 48, 210, 28, spec["soft"])])
                for y in (326, 510, 610):
                    paper.append(_rect("rule", 80, y, 1120, 2, spec["soft"]))
            elif template_id == "classroom-story":
                paper.extend([_rect("frame", 40, 56, 1200, 248, spec["accent"]),
                              _rect("title-panel", 48, 64, 1184, 232, spec["soft"]),
                              _rect("story-panel", 48, 326, 1184, 298, "#FFFFFF"),
                              _rect("bottom", 0, 662, 1280, 58, spec["accent"])])
                title["alignment"]["horizontal"] = "center"
            elif template_id == "training-case":
                paper.extend([_rect("dossier", 0, 0, 1280, 310, spec["accent"]),
                              _rect("evidence", 48, 326, 1184, 190, "#FFFFFF"),
                              _rect("file-tab", 80, 40, 160, 10, "#7ABBB4")])
                title["font"]["color"] = "#FFFFFF"
            else:
                paper.extend([_rect("rail", 0, 0, 30, 720, spec["accent"]),
                              _rect("goal", 48, 326, 1184, 184, "#FFFFFF"),
                              _rect("usage", 48, 524, 1184, 90, spec["soft"])])
                for index in range(5):
                    paper.append(_rect("route", 80 + index * 230, 648, 190, 12, spec["accent"]))
            continue

        if template_id == "classroom-nature":
            paper.extend([_rect("spine", 0, 0, 24, 720, spec["accent"]),
                          _rect("page", 40, 164, 1208, 456, "#FFFFFF"),
                          _rect("tab", 48, 146, 190, 12, spec["accent"])])
        elif template_id == "classroom-story":
            paper.extend([_rect("top", 0, 0, 1280, 12, spec["accent"]),
                          _rect("cue-panel", 32, 628, 1216, 80, spec["soft"])])
        elif template_id == "training-case":
            paper.append(_rect("header", 0, 0, 1280, 158, spec["accent"]))
            title["font"]["color"] = "#FFFFFF"
        else:
            paper.extend([_rect("accent", 48, 144, 140, 12, spec["accent"]),
                          _rect("footer", 0, 624, 1280, 96, spec["soft"])])

        if "_cards_" in layout["id"]:
            count = int(layout["id"].rsplit("_", 1)[-1])
            for index in range(count):
                card = components[f"card_{index}"]
                picture, caption = card["elements"]
                x, width = picture["position"]["x"], picture["size"]["width"]
                if roomy:
                    _place(picture, x, 182, width, 116)
                    _place(caption, x, 316, width, 298)
                elif template_id == "classroom-nature":
                    _place(picture, x + 12, 194, width - 24, 236)
                    _place(caption, x + 12, 450, width - 24, 164)
                elif template_id == "classroom-story":
                    _place(picture, x + 12, 186, width - 24, 264)
                    _place(caption, x + 12, 472, width - 24, 142)
                elif template_id == "training-case" and count in (2, 4):
                    row, col = divmod(index, 2)
                    x = 48 + col * 608
                    y = 178 + row * 220
                    width = 576
                    _place(picture, x + 12, y + 12, 144, 188 if count == 4 else 402)
                    _place(caption, x + 176, y + 12, 388, 188 if count == 4 else 402)
                elif template_id == "training-action" and count <= 3:
                    # Image, ordinal and action form a vertical sequence of rows.
                    height = 430 / count - 12
                    y = 180 + index * 430 / count
                    x, width = 48, 1184
                    _place(picture, 1040, y, 192, height)
                    _place(caption, 124, y, 880, height)
                    if index == 0:
                        paper.append(_rect("track", 106, 180, 3, 418, spec["accent"]))
                    paper.append(_number(index + 1, 48, y, spec["accent"]))
                # All panels sit behind content, never mask an illustration.
                if template_id == "classroom-story":
                    p = picture["position"]; z = picture["size"]
                    paper.extend([_rect("frame", p["x"] - 6, p["y"] - 6, z["width"] + 12, z["height"] + 12, spec["accent"]),
                                  _rect("panel", p["x"] - 2, p["y"] - 2, z["width"] + 4, z["height"] + 4, "#FFFFFF")])
                elif template_id == "training-case":
                    p = caption["position"]; z = caption["size"]
                    paper.append(_rect("evidence", p["x"] - 8, p["y"] - 6, z["width"] + 16, z["height"] + 12, "#FFFFFF"))
                else:
                    paper.append(_rect("card-rule", x, 618, width, 3, spec["accent"]))
                caption["alignment"]["vertical"] = "top"
            continue

        count = int(layout["id"].rsplit("_", 1)[-1])
        scene = components["scene"]["elements"][0]
        if not count:
            _place(scene, 48, 178, 1184, 430)
        elif roomy or template_id == "training-action":
            _place(scene, 932, 178, 300, 430)
        elif template_id == "classroom-story":
            _place(scene, 56, 180, 1168, 214 if count > 3 else 240)
        elif template_id == "classroom-nature":
            _place(scene, 56, 178, 664 if count <= 3 else 484, 430)
        else:
            _place(scene, 48, 178, 324, 430)
        for index in range(count):
            text = components[f"point_{index}"]["elements"][0]
            text["alignment"]["vertical"] = "top"
            if template_id == "classroom-story" and not roomy:
                cols = min(count, 3)
                rows = (count + cols - 1) // cols
                width = (1184 - (cols - 1) * 28) / cols
                row, col = divmod(index, cols)
                _place(text, 48 + col * (width + 28), 414 + row * 104 if rows == 2 else 442,
                       width, 96 if rows == 2 else 172)
            else:
                rows = count if count <= 3 else (count + 1) // 2
                col, row = (0, index) if count <= 3 else divmod(index, rows)
                if roomy:
                    x, width, gap = 48, (848 if count <= 3 else 410), 438
                elif template_id == "classroom-nature":
                    x, width, gap = (756 if count <= 3 else 568), (476 if count <= 3 else 320), 344
                elif template_id == "training-case":
                    x, width, gap = 420, (812 if count <= 3 else 392), 420
                else:
                    x, width, gap = 112, (776 if count <= 3 else 356), 420
                _place(text, x + col * gap, 178 + row * 430 / rows, width, 430 / rows - 12)
                if template_id == "training-action" and not roomy:
                    paper.append(_number(index + 1, x + col * gap - 64, 178 + row * 430 / rows, spec["accent"]))
                if template_id == "classroom-nature":
                    paper.append(_rect("rule", x + col * gap, 178 + (row + 1) * 430 / rows - 6, width, 2, spec["soft"]))
                if template_id == "training-case":
                    paper.append(_rect("evidence", x + col * gap - 8, 174 + row * 430 / rows, width + 16, 430 / rows - 8, "#FFFFFF"))
        p, z = scene["position"], scene["size"]
        if template_id == "classroom-story":
            paper.extend([_rect("frame", p["x"] - 6, p["y"] - 6, z["width"] + 12, z["height"] + 12, spec["accent"]),
                          _rect("inner", p["x"] - 2, p["y"] - 2, z["width"] + 4, z["height"] + 4, "#FFFFFF")])
        elif template_id == "training-action":
            paper.append(_rect("result", p["x"] - 8, p["y"] - 4, z["width"] + 16, z["height"] + 8, "#FFFFFF"))
    picture_styles = {
        "classroom-nature": "自然观察手册插画，草木绿和浅米色，水彩叶脉与自然形态细节清楚。",
        "classroom-story": "绘本分镜插画，深青色清晰轮廓、明黄与珊瑚色，角色动作和表情鲜明。",
        "training-case": "教育案例档案插画，雾蓝灰与深蓝，突出真实观察行为和客观证据。",
        "training-action": "教育行动指南插画，陶土红、暖白和浅棕，突出教师实施支持的具体动作。",
    }
    for layout in template.layouts["layouts"]:
        for component in layout["components"]:
            for element in component["elements"]:
                if element["type"] == "image":
                    element["prompt"] = picture_styles[template_id]
    template.layouts = SlideLayouts.model_validate(template.layouts).model_dump(
        mode="json", by_alias=True, exclude_none=True,
    )
    template.assets = {
        "template_id": template_id, "images": [], "fonts": {},
        "thumbnail": f"/static/templates/{template_id}.svg",
        "template_metadata": {"audiences": [spec["audience"]], "allow_charts": False,
                              "auto_match": True, "quality_status": "candidate"},
    }
    return template
