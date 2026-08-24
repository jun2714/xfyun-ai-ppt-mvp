from __future__ import annotations

import os
import re

LIBRARY_CATEGORIES = (
    "健康",
    "语言",
    "社会",
    "科学",
    "艺术",
    "家园共育",
    "节日",
    "其他",
)
LIBRARY_AGE_GROUPS = ("小班", "中班", "大班", "混龄")
LIBRARY_SEASONS = ("春季", "秋季", "不限")
LIBRARY_SCENES = ("教学", "家长会", "公开课", "其他")


def guess_library_tags(filename: str | None, title: str | None = None) -> dict[str, str]:
    text = f"{filename or ''} {title or ''}"
    stem = re.sub(r"\.pptx$", "", os.path.basename(filename or title or ""), flags=re.I)
    stem = re.sub(r"^\d+\s*", "", stem).strip(" -_《》")

    age_group = "混龄"
    if "小班" in text:
        age_group = "小班"
    elif "中班" in text:
        age_group = "中班"
    elif "大班" in text:
        age_group = "大班"

    season = "不限"
    if any(token in text for token in ("春季", "春学期", "下学期", "春启")):
        season = "春季"
    elif any(token in text for token in ("秋季", "秋学期", "上学期", "开学")):
        season = "秋季"

    scene = "其他"
    if any(token in text for token in ("公开课", "观摩课")):
        scene = "公开课"
    elif any(token in text for token in ("家长会", "家长", "毕业", "幼小衔接", "衔接")):
        scene = "家长会"
    elif "教学" in text:
        scene = "教学"

    category = "其他"
    if scene == "家长会":
        category = "家园共育"
    elif any(token in text for token in ("健康", "卫生", "安全")):
        category = "健康"
    elif any(token in text for token in ("语言", "阅读", "绘本")):
        category = "语言"
    elif any(token in text for token in ("社会", "交往")):
        category = "社会"
    elif any(token in text for token in ("科学", "探索")):
        category = "科学"
    elif any(token in text for token in ("艺术", "美术", "音乐")):
        category = "艺术"
    elif any(token in text for token in ("节日", "新年", "端午", "中秋")):
        category = "节日"

    return {
        "title": stem or (title or "未命名课件"),
        "category": category,
        "age_group": age_group,
        "season": season,
        "scene": scene,
    }


def normalize_library_choice(value: str | None, allowed: tuple[str, ...], fallback: str) -> str:
    text = (value or "").strip()
    return text if text in allowed else fallback
