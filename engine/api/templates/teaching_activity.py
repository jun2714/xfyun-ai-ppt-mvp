"""Two distinct activity packs built from native editable elements.

Interaction is teacher-led and page-based; no HTML-only controls or painted text.
Exact caption/asset bindings and safe roomy alternatives remain mandatory.
"""
import copy

from templates.ai_visual_default import _component
from templates.kindergarten_classroom import _label, _picture, classroom_layouts
from templates.education_variants import _rect
from services.teaching_interaction_service import ROLE_LABELS


ACTIVITY_STYLES = {
    "classroom-game": dict(
        name="游戏探索 · 观察与挑战", background="#FFF8ED", ink="#20374D",
        accent="#C75330", soft="#F7DFC4", secondary="#D8EAE5",
        description="温暖任务卡与大图观察、比较、选择、排序、猜谜揭晓和回顾；支持教师带领的课堂互动。",
        image_style="温暖清晰的二维剪纸绘本，柔和纸张肌理、深蓝轮廓与珊瑚色点缀；保留教学对象本色，不添加无关角色或装饰。",
    ),
    "training-workshop": dict(
        name="教研工作坊 · 证据与共创", background="#F5F4F8", ink="#302B48",
        accent="#65518A", soft="#E6E0EE", secondary="#E2EBE8",
        description="专业工作坊构图：证据对照、观点讨论、行动步骤与反思记录；独立讲稿和充足的正文空间。",
        image_style="专业教育编辑插画，淡紫灰纸面、墨紫与低饱和青绿；呈现客观观察证据和真实教师工作，不使用儿童闯关或商务海报风格。",
    ),
}


def _text(name, x, y, w, h, spec, size=32, *, bold=False):
    value = _label(name, x, y, w, h, size, color=spec["ink"])
    value["font"]["bold"] = bold
    value["alignment"]["vertical"] = "top"
    return value


def _base(spec, role, teacher):
    paper = [_rect("paper", 0, 0, 1280, 720, spec["background"])]
    if teacher:
        paper.extend([_rect("spine", 0, 0, 16, 720, spec["accent"]),
                      _rect("rule", 48, 154, 1184, 3, spec["accent"])])
    else:
        paper.extend([_rect("top-accent", 48, 14, 100, 6, spec["accent"]),
                      _rect("invitation-panel", 32, 630, 1216, 82, spec["soft"])])
    badge = _text("role-label", 1010, 35, 222, 48, spec, bold=True)
    badge["runs"] = [{"text": ROLE_LABELS[role]}]
    badge["decorative"] = True
    return [_component("paper", "独立配色、页面层级与活动角色装饰背景", paper),
            _component("role_badge", "可编辑的教学活动角色标记，不包含答案", [badge]),
            _component("heading", "保留老师已确认的完整页面标题文字", [
                _text("title", 48, 30, 936, 126, spec, 48, bold=True)]),
            _component("invitation", "保留参与者操作短句，详细指导存入备注", [
                _text("cue", 48, 640, 1184, 70, spec)])]


def _metadata(role, count, images):
    return dict(capabilities=["teacher-led", role],
                contentShape=dict(minItems=count, maxItems=count, textBlocks=count + 2, imageSlots=images),
                media=dict(framedImageSlots=images, required=True),
                readability=dict(minimumFontSize=32, maximumVisibleCharacters=1600),
                qualityStatus="candidate")


def _scene(prefix, spec, role, count, teacher, *, roomy=False):
    components = _base(spec, role, teacher)
    if roomy:
        components[1]["elements"][0]["runs"] = [{"text": "思考记录" if teacher else "继续探索"}]
    paper = components[0]["elements"]
    if roomy:
        image_box, text_box, cols = (948, 182, 284, 426), (48, 182, 868, 426), (1 if count <= 3 else 2)
    elif role == "observe":
        image_box, text_box, cols = ((48, 180, 720, 430), (808, 180, 424, 430), 1)
    elif role == "compare":
        image_box, text_box, cols = (48, 176, 1184, 240), (48, 440, 1184, 176), min(max(count, 1), 3)
    elif role in {"choice", "question"}:
        image_box, text_box, cols = (48, 186, 660, 420), (756, 186, 476, 420), 1
    elif role == "reveal":
        image_box, text_box, cols = (48, 184, 500, 424), (596, 184, 636, 424), 1
        paper.append(_rect("reveal-panel", 576, 172, 672, 446, spec["secondary"]))
    elif role == "sequence":
        image_box, text_box, cols = (48, 192, 360, 400), (464, 184, 768, 424), (1 if count <= 3 else 2)
    elif role == "recap":
        image_box, text_box, cols = (48, 184, 352, 424), (440, 184, 792, 424), (1 if count < 3 else 2)
    else:  # workshop discussion: a generous writing area beside evidence
        image_box, text_box, cols = (824, 184, 408, 424), (48, 184, 728, 424), (1 if count <= 3 else 2)
    if teacher and not roomy:
        # Workshop evidence occupies a separate rail; classroom activities use
        # larger central scenes. The two packs differ beyond their palette.
        if role == "observe":
            image_box, text_box, cols = (824, 180, 408, 430), (48, 180, 728, 430), 1
        elif role == "compare":
            image_box, text_box, cols = (48, 176, 460, 438), (556, 176, 676, 438), min(max(count, 1), 2)
    if not count:
        image_box = (48, 180, 1184, 430)
    components.append(_component("scene", "完整呈现本页教学对象或案例证据的图片", [_picture("visual", *image_box)]))
    x, y, w, h = text_box
    rows = max(1, (count + cols - 1) // cols)
    cw, ch = (w - 24 * (cols - 1)) / cols, (h - 16 * (rows - 1)) / rows
    for index in range(count):
        row, col = divmod(index, cols)
        px, py = x + col * (cw + 24), y + row * (ch + 16)
        if role in {"choice", "question", "recap", "sequence", "discuss"}:
            paper.append(_rect(f"point-panel-{index}", px - 8, py - 4, cw + 16, ch + 8,
                               "#FFFFFF" if teacher else spec["secondary"]))
        components.append(_component(f"point_{index}", "按原顺序保留完整教学短句或研讨证据", [
            _text("text", px, py, cw, ch, spec)]))
    variant = "roomy" if roomy else role
    return dict(id=f"{prefix}_scene_{variant}_{count}",
                description=f"{spec['name']}：{ROLE_LABELS[role]}，{'宽松正文' if roomy else '教学场景'}与{count}项完整文案。",
                components=components, metadata=_metadata(role, count, 1))


def _cards(prefix, spec, role, count, teacher, *, roomy=False):
    components = _base(spec, role, teacher)
    if roomy:
        components[1]["elements"][0]["runs"] = [{"text": "思考记录" if teacher else "继续探索"}]
    paper = components[0]["elements"]
    # Native numbering is intentionally absent: item order must not reveal a
    # sequence answer or imply a correct choice on a question page.
    grid = role in {"choice", "recap"} and count > 2 and not roomy
    cols = 2 if grid else count
    rows = (count + cols - 1) // cols
    width = (1184 - 24 * (cols - 1)) / cols
    height = (438 - 20 * (rows - 1)) / rows
    for index in range(count):
        row, col = divmod(index, cols)
        x, y = 48 + col * (width + 24), 176 + row * (height + 20)
        paper.append(_rect(f"card-panel-{index}", x - 6, y - 4, width + 12, height + 8,
                           "#FFFFFF" if teacher else (spec["soft"] if index % 2 else spec["secondary"])))
        if grid:
            picture = _picture("visual", x + 8, y + 8, width * .44, height - 16)
            caption = _text("text", x + width * .49, y + 8, width * .51 - 8, height - 16, spec)
        else:
            image_height = 108 if roomy else (204 if teacher else 258)
            if role == "sequence" and not roomy:
                image_height -= (index % 2) * 32
            picture = _picture("visual", x + 10, y + 8, width - 20, image_height)
            caption = _text("text", x + 10, y + image_height + 28, width - 20,
                            height - image_height - 36, spec)
        components.append(_component(f"card_{index}", "图片仅绑定自己的完整原文，不按素材顺序猜配", [picture, caption]))
    variant = "roomy" if roomy else role
    return dict(id=f"{prefix}_cards_{variant}_{count}",
                description=f"{spec['name']}：{ROLE_LABELS[role]}，{count}个独立图文单元{'，宽松正文' if roomy else ''}。",
                components=components, metadata=_metadata(role, count, count))


def build_activity_template(template_id):
    from models.sql.template_v2 import TemplateV2
    from templates.v2.models.layouts import SlideLayouts

    spec = ACTIVITY_STYLES[template_id]
    teacher = template_id == "training-workshop"
    prefix = "classroom_training" if teacher else "classroom"
    cover = copy.deepcopy(classroom_layouts()[0])
    cover["id"] = f"{prefix}_cover"
    for component in cover["components"]:
        for element in component["elements"]:
            if component["id"] == "paper":
                element["fill"]["color"] = spec["background"]
            if element["type"] == "text":
                element["font"]["color"] = spec["ink"]
            if component["id"] == "cover_panel":
                element["fill"]["color"] = spec["background"]
    cover["components"][2]["elements"].append(_rect("cover-accent", 592, 76, 140, 8, spec["accent"]))
    layouts = [cover]
    for count in range(7):
        for role in ROLE_LABELS:
            layouts.append(_scene(prefix, spec, role, count, teacher))
        layouts.append(_scene(prefix, spec, "discuss" if teacher else "observe", count, teacher, roomy=True))
    for count in (2, 3, 4):
        for role in ROLE_LABELS:
            layouts.append(_cards(prefix, spec, role, count, teacher))
        layouts.append(_cards(prefix, spec, "compare", count, teacher, roomy=True))
    for layout in layouts:
        for component in layout["components"]:
            for element in component["elements"]:
                if element["type"] == "image":
                    element["prompt"] = spec["image_style"]
    payload = SlideLayouts.model_validate({"layouts": layouts}).model_dump(mode="json", by_alias=True, exclude_none=True)
    return TemplateV2(id=template_id, name=spec["name"], description=spec["description"],
                      layouts=payload, is_default=True,
                      assets=dict(template_id=template_id, images=[], fonts={},
                                  thumbnail=f"/static/templates/{template_id}.svg",
                                  template_metadata=dict(audiences=["teacher" if teacher else "child"],
                                                         auto_match=True, allow_charts=False,
                                                         quality_status="candidate")))
