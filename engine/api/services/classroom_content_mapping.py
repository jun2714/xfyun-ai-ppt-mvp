"""Deterministic screen/teacher/visual mapping for the code-owned classroom pack."""
import re

from templates.kindergarten_classroom import CLASSROOM_LAYOUT_PREFIX
from utils.template_text_capacity import locked_text_fits_field


def _lines(content):
    # Match reviewed Markdown normalization without importing the LLM module.
    lines = []
    for raw in content.splitlines():
        line = re.sub(r"^\s*(?:#{1,6}\s*|[-*+•]\s+|\d+[.)]\s+)", "", raw).strip()
        line = line.replace("**", "").replace("__", "")
        if line:
            lines.append(line)
    return lines


def screen_roles(outline):
    contract = outline.content_contract
    if not contract or not contract.preserve_visible_copy:
        raise ValueError("幼教课堂版式需要已确认的大纲文案。")
    current = _lines(outline.content)
    if not current:
        raise ValueError("课堂页面没有屏幕内容。")
    snapshot = [contract.screen_title, *contract.screen_points]
    if contract.screen_instruction:
        snapshot.append(contract.screen_instruction)
    if current == snapshot:
        return current[0], list(contract.screen_points), contract.screen_instruction or "", True
    # Teachers may edit Markdown. Never restore stale title/points from metadata.
    # Exact image-caption bindings are usable only if the caption still exists.
    return current[0], current[1:], "", False


def _bound_assets(contract, points):
    assets = []
    for point in points:
        matches = [asset for asset in contract.asset_contracts
                   if asset.audience_text == point and asset.role != "background"]
        if len(matches) != 1:
            return []
        assets.append(matches[0])
    # No duplicate caption or silent omission of another required visual.
    if len(set(points)) != len(points) or len(assets) != len(contract.asset_contracts):
        return []
    return assets


def preferred_classroom_layout(outline, slide_index=0):
    _, points, _, unchanged = screen_roles(outline)
    if unchanged and len(points) in (2, 3, 4) and _bound_assets(outline.content_contract, points):
        return f"classroom_cards_{len(points)}"
    side = "left" if slide_index % 2 == 0 else "right"
    return f"classroom_scene_{side}_{len(points)}"


def _image_value(schema, prompt):
    result = {}
    for key in schema.get("properties", {}):
        if key in {"image_prompt", "__image_prompt__"}:
            result[key] = prompt
        elif key in {"image_url", "__image_url__"}:
            result[key] = ""
    return result


def _prompt(assets, title, points):
    subjects = "；".join(f"{a.semantic_label}：{a.description or ''}" for a in assets)
    return (
        f"本页教学主题：{title}。对应屏幕内容：{'；'.join(points)}。"
        f"必须看到的教学对象与动作：{subjects or title}。"
        "统一二维儿童绘本，柔和水粉和彩铅，奶油白、薄荷绿、暖珊瑚配色；"
        "主体完整、特征准确、背景简洁；不要摄影、3D、文字、字母、数字、标签或水印。"
    )


def build_classroom_content(schema, outline):
    layout_id = str(schema.get("title") or "")
    if not layout_id.startswith(CLASSROOM_LAYOUT_PREFIX):
        raise ValueError("不是课堂专用版式。")
    title, points, cue, unchanged = screen_roles(outline)
    contract = outline.content_contract
    cards = layout_id.startswith("classroom_cards_")
    bound = _bound_assets(contract, points) if cards else []
    if cards and not bound:
        raise ValueError("图文卡缺少明确的一对一语义绑定，不能按图片顺序猜测配对。")
    if cards and not unchanged:
        raise ValueError("大纲已修改，请重新匹配课堂版式，不能沿用旧图文卡绑定。")
    if int(layout_id.rsplit("_", 1)[-1]) != len(points):
        raise ValueError("课堂版式的内容单元数与已确认文案不一致。")
    result = {}
    for component, component_schema in schema.get("properties", {}).items():
        fields = component_schema.get("properties", {})
        values = {}
        for key, field in fields.items():
            if component == "heading" and key == "title":
                value = title
            elif component == "invitation" and key == "cue":
                value = cue
            elif component.startswith("point_") and key == "text":
                value = points[int(component.split("_")[-1])]
            elif component.startswith("card_"):
                index = int(component.split("_")[-1])
                value = (points[index] if key == "text" else
                         _image_value(field, _prompt([bound[index]], title, [points[index]])))
            elif component == "scene" and key == "visual":
                # Edited content supersedes stale asset instructions in scene mode.
                value = _image_value(field, _prompt(
                    contract.asset_contracts if unchanged else [], title, points))
            else:
                raise ValueError(f"未知课堂字段 {component}.{key}")
            if isinstance(value, str) and not locked_text_fits_field(value, field):
                raise ValueError(f"课堂文案在大字号下放不进 {component}.{key}，请在大纲中拆页，不能自动缩写。")
            values[key] = value
        result[component] = values
    metadata = contract.model_dump(mode="json")
    if contract.classroom_role in {"guess-shadow", "guess-partial"}:
        concealment = ("只展示主体剪影，不显示内部纹理或完整彩色答案。"
                       if contract.classroom_role == "guess-shadow" else
                       "只显示描述中的局部线索，其他部分必须遮挡，不能展示完整答案主体。")
        for component in result.values():
            visual = component.get("visual") if isinstance(component, dict) else None
            if isinstance(visual, dict) and "image_prompt" in visual:
                visual["image_prompt"] += concealment
    metadata["classroom_mapping_version"] = 1
    metadata["screen_title"] = title
    metadata["screen_points"] = points
    metadata["screen_instruction"] = cue
    if not unchanged:
        metadata["required_asset_semantics"] = []
        metadata["asset_contracts"] = []
    result["__content_contract__"] = metadata
    note = contract.teacher_note or ""
    if contract.interaction_instruction and contract.interaction_instruction not in note:
        note += "\n课堂操作：" + contract.interaction_instruction
    result["__speaker_note__"] = note.strip()
    return result
