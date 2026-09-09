from __future__ import annotations

import re
from typing import Literal

from models.presentation_outline_model import (
    PresentationOutlineModel,
    SlideAssetContract,
    SlideContentContract,
)


KindergartenVisualMode = Literal["template", "ai-background"]
KindergartenContentMode = Literal["classroom", "training"]
AI_BACKGROUND_TEMPLATE_NAME = "ai-visual"


_DOMAIN_STYLE_BIBLES: dict[str, str] = {
    "science": (
        "清新自然儿童绘本插画，柔和日光，叶绿、天空蓝、奶油白与少量暖黄，"
        "主体真实特征清楚但不过度写实，画面有探索感和留白"
    ),
    "language": (
        "温暖故事绘本插画，奶油纸张质感，柔和暖光，杏色、浅蓝、草绿点缀，"
        "角色表情自然，叙事感强但画面不过度拥挤"
    ),
    "math": (
        "明亮幼儿数学绘本与几何纸艺结合，蓝绿、橙黄、奶油白，结构清楚，"
        "物体轮廓和数量关系易辨认，避免成人化信息图"
    ),
    "art": (
        "轻手绘与纸张拼贴质感，奶油白底色搭配明快但克制的儿童色彩，"
        "保留手作温度和大面积呼吸感，不模仿任何具体艺术家"
    ),
    "social": (
        "温暖生活绘本插画，柔和自然光，杏色、浅绿、天空蓝，"
        "中国幼儿园日常场景，人物友好自然，情绪表达清楚"
    ),
    "health": (
        "清爽明亮的幼儿生活插画，薄荷绿、天空蓝、暖橙与白色，"
        "卫生健康动作清楚，场景干净安全，避免医疗宣传风"
    ),
    "comprehensive": (
        "明亮童趣的中国幼儿园绘本插画，柔和自然光，奶油白、天空蓝、浅绿与暖橙，"
        "造型统一、画面干净、适合课堂投影"
    ),
}

_TRAINING_STYLE_BIBLE = (
    "专业清晰的幼儿园教研培训视觉，浅米白、松石绿、雾蓝与少量暖灰，"
    "层次明确、留白充足，适合教师分享和会议投影，避免童趣卡通与成人商务海报感"
)


def get_kindergarten_visual_style_summary(
    *,
    domain: str,
    visual_style_hint: str | None = None,
    content_mode: KindergartenContentMode = "classroom",
) -> str:
    base = (
        _TRAINING_STYLE_BIBLE
        if content_mode == "training"
        else _DOMAIN_STYLE_BIBLES.get(domain, _DOMAIN_STYLE_BIBLES["comprehensive"])
    )
    hint = " ".join((visual_style_hint or "").strip().split())
    if not hint:
        return base
    return f"{base}；用户视觉偏好：{hint[:120]}"


def _visible_slide_title(content: str, index: int) -> str:
    for raw_line in content.splitlines():
        line = raw_line.strip().lstrip("#").strip()
        if not line:
            continue
        line = line.replace("**", "").replace("__", "").replace("*", "")
        return line[:36]
    return f"第{index + 1}页"


def _background_scene_description(
    *,
    topic: str,
    slide_title: str,
    relationship: str,
    interaction_type: str,
    slide_index: int,
    content_mode: KindergartenContentMode = "classroom",
) -> str:
    if content_mode == "training":
        if slide_index == 0:
            scene = (
                "简洁教研封面插画，用主题墙、积木、图书、成长线索等小型教育元素"
                "环绕画面边缘，中央大面积干净留白用于标题；不做照片拼贴、前后对比、"
                "会议人物合影或复杂教室全景"
            )
        elif relationship in {"comparison", "classification", "matching"}:
            scene = "真实案例对照场景，清楚呈现现状与改进后的环境差异"
        elif relationship == "sequence" or interaction_type == "sequence":
            scene = "策略实施路径场景，步骤关系清楚并保留文字安全区"
        else:
            scene = "中国幼儿园教师观察、研讨或调整课程环境的真实工作场景"
        return f"围绕《{topic}》与“{slide_title}”设计{scene}"
    if slide_index == 0:
        scene = "开场全景，主题核心对象自然出现，具有邀请孩子进入课堂的故事感"
    elif relationship == "question" or interaction_type in {"choose", "guess"}:
        scene = "互动提问场景，背景低细节、主体明确，避免提前暴露答案"
    elif relationship == "reveal":
        scene = "答案揭晓场景，情绪更明亮积极，但仍与前一页保持同一世界观"
    elif relationship in {"comparison", "classification", "matching"}:
        scene = "教学操作场景，左右或多区域关系清晰，关键对象彼此不遮挡"
    elif relationship == "sequence" or interaction_type == "sequence":
        scene = "步骤推进场景，画面有自然方向感和清晰前后关系"
    elif relationship == "story":
        scene = "绘本叙事场景，保留角色行动空间和清楚的前中后景"
    elif interaction_type in {"move", "imitate"}:
        scene = "动作示范场景，人物或主体全身完整，动作路径清楚，留出活动提示区域"
    else:
        scene = "课堂观察场景，核心对象突出，环境信息用于帮助理解而不喧宾夺主"
    return f"围绕《{topic}》与“{slide_title}”设计{scene}"


def _background_semantic_label(*, topic: str, slide_title: str, slide_index: int) -> str:
    """Keep exact-match asset semantics concise for reliable image preflight."""
    base = slide_title.strip() or topic.strip() or f"第{slide_index + 1}页"
    base = re.sub(r"[\s#*_`]+", "", base)
    base = re.sub(r"[，。！？、：:；;（）()【】《》“”‘’\"'·/\\\\-]+", "", base)
    return f"{(base or f'第{slide_index + 1}页')[:24]}第{slide_index + 1}页背景"


def _safe_area_for_slide(index: int, relationship: str) -> str:
    if index == 0:
        return "center"
    if relationship in {"comparison", "classification", "matching"}:
        return "center"
    return "left" if index % 2 else "right"


def _append_unique(values: list[str], value: str, *, max_items: int) -> bool:
    key = value.casefold()
    if any(existing.casefold() == key for existing in values):
        return True
    if len(values) >= max_items:
        return False
    values.append(value)
    return True


def apply_ai_background_visual_plan(
    outline: PresentationOutlineModel,
    *,
    topic: str,
    domain: str,
    visual_style_hint: str | None = None,
    content_mode: KindergartenContentMode = "classroom",
) -> PresentationOutlineModel:
    """Add one generated full-canvas background contract to every slide.

    The visible slide copy is unchanged. The hidden contract gives the downstream
    content/image stages a stable art direction, a page-specific scene and a text
    safe area. Existing teaching-object contracts are preserved, so multi-item and
    game pages can still request additional framed/cutout assets when the selected
    layout provides those slots.
    """
    planned = outline.model_copy(deep=True)
    style_bible = get_kindergarten_visual_style_summary(
        domain=domain,
        visual_style_hint=visual_style_hint,
        content_mode=content_mode,
    )

    for index, slide in enumerate(planned.slides):
        contract = (
            slide.content_contract.model_copy(deep=True)
            if slide.content_contract is not None
            else SlideContentContract()
        )
        relationship = contract.relationship or "unknown"
        interaction_type = contract.interaction_type or "none"
        title = _visible_slide_title(slide.content, index)
        safe_area = _safe_area_for_slide(index, relationship)
        semantic_label = _background_semantic_label(
            topic=topic,
            slide_title=title,
            slide_index=index,
        )[:160]
        scene = _background_scene_description(
            topic=topic,
            slide_title=title,
            relationship=relationship,
            interaction_type=interaction_type,
            slide_index=index,
            content_mode=content_mode,
        )
        description = (
            f"16:9{'幼儿园教研培训' if content_mode == 'training' else '幼儿园课堂'}全屏背景。"
            f"统一视觉规范：{style_bible}。"
            f"本页场景：{scene}。文字安全区位于{safe_area}侧/区域，安全区必须低细节、"
            "低对比且不得放置关键主体；背景只生成与本页主题一致的场景、人物或物体，不得自行绘制"
            "白色矩形、信息卡、边框、表格、标题栏、文本框或留白占位框；"
            "画面不得出现任何文字、字母、数字、Logo、"
            "水印、签名或伪文字；不得出现知名IP角色或品牌元素。"
        )[:800]

        contract.requires_images = True
        contract.media_role = (
            "background" if contract.media_role in {"none", "background"} else "mixed"
        )
        if not _append_unique(
            contract.required_asset_semantics,
            semantic_label,
            max_items=16,
        ):
            raise ValueError(
                f"第 {index + 1} 页图片语义契约已达到上限，无法追加 AI 背景契约。"
            )
        if not any(
            item.role == "background" and item.semantic_label == semantic_label
            for item in contract.asset_contracts
        ):
            if len(contract.asset_contracts) >= 16:
                raise ValueError(
                    f"第 {index + 1} 页图片资产契约已达到上限，无法追加 AI 背景契约。"
                )
            contract.asset_contracts.insert(
                0,
                SlideAssetContract(
                    planning_slot="ai_background",
                    semantic_label=semantic_label,
                    description=description,
                    expected_count=1,
                    role="background",
                    qa_required=True,
                ),
            )
        _append_unique(
            contract.preferred_layout_capabilities,
            "scene",
            max_items=8,
        )
        # Re-validate the mutated contract before persistence. This catches future
        # field-limit changes here rather than after the teacher has reviewed it.
        slide.content_contract = SlideContentContract.model_validate(
            contract.model_dump(mode="json")
        )

    return planned
