from __future__ import annotations

from dataclasses import dataclass

from models.kindergarten_lesson_plan import KindergartenLessonPlan


AUTO_TEMPLATE_NAME = "auto"
KINDERGARTEN_TEMPLATE_FALLBACK = "standard"

# Stable tie-break order. Lower rank wins only when scores are equal.
_TEMPLATE_PRIORITY = {
    "dynamic": 20,
    "modern": 30,
    "swift": 40,
    "momentum": 50,
    "standard": 60,
}

_DOMAIN_WEIGHTS: dict[str, dict[str, int]] = {
    "science": {"dynamic": 9, "standard": 1},
    "math": {"dynamic": 5, "standard": 3},
    "language": {"modern": 7, "standard": 2},
    "social": {"modern": 4, "momentum": 2, "standard": 3},
    "art": {"momentum": 9, "standard": 1},
    "health": {"standard": 9},
    "comprehensive": {"standard": 3},
}

_TEMPLATE_TERMS: dict[str, tuple[str, ...]] = {
    "dynamic": (
        "科学",
        "探索",
        "自然",
        "观察",
        "发现",
        "植物",
        "动物",
        "实验",
        "天气",
        "昆虫",
        "宇宙",
        "种子",
        "叶子",
        "花朵",
        "春天",
        "夏天",
        "秋天",
        "冬天",
    ),
    "modern": (
        "绘本",
        "故事",
        "童话",
        "阅读",
        "语言",
        "讲述",
        "情绪",
        "情感",
        "角色",
        "成长故事",
    ),
    "swift": (
        "游戏",
        "互动",
        "猜一猜",
        "找一找",
        "配对",
        "闯关",
        "问答",
        "律动",
        "抢答",
        "挑战",
        "找不同",
    ),
    "momentum": (
        "亲子",
        "家园",
        "手工",
        "艺术",
        "美术",
        "音乐",
        "节日",
        "春节",
        "元宵",
        "端午",
        "中秋",
        "国庆",
        "六一",
        "毕业",
        "运动会",
    ),
    "standard": (
        "安全",
        "卫生",
        "健康",
        "生活习惯",
        "礼仪",
        "规则",
        "常规",
        "区角",
        "认识",
        "认知",
    ),
}

_GAME_SLIDE_TYPES = {
    "guess-partial",
    "guess-shadow",
    "memory-show",
    "memory-missing",
    "matching",
    "classification",
    "sequence",
}
_STORY_SLIDE_TYPES = {"story-intro", "ending-scene"}
_EXPLORATION_SLIDE_TYPES = {
    "knowledge-single",
    "image-observation",
    "compare",
}


@dataclass(frozen=True)
class KindergartenTemplateRoutingDecision:
    template: str
    reason: str
    scores: dict[str, int]


def resolve_kindergarten_template(
    plan: KindergartenLessonPlan,
    requested_template: str | None,
    *,
    instructions: str | None = None,
) -> KindergartenTemplateRoutingDecision:
    """Resolve `auto` to a stable bundled kindergarten visual family.

    Explicit template selections are never rewritten. Automatic routing is based
    on teaching domain, actual lesson slide semantics, and visible topic text. The
    result is deterministic so retries of the same reviewed lesson do not jump
    between unrelated visual families.
    """
    requested = (requested_template or AUTO_TEMPLATE_NAME).strip()
    if requested and requested.casefold() != AUTO_TEMPLATE_NAME:
        return KindergartenTemplateRoutingDecision(
            template=requested,
            reason="manual-selection",
            scores={},
        )

    scores = {name: 0 for name in _TEMPLATE_PRIORITY}
    reasons: dict[str, list[str]] = {name: [] for name in _TEMPLATE_PRIORITY}

    domain = plan.meta.domain
    for template, weight in _DOMAIN_WEIGHTS.get(domain, {}).items():
        scores[template] += weight
        reasons[template].append(f"domain:{domain}+{weight}")

    game_count = sum(slide.slide_type in _GAME_SLIDE_TYPES for slide in plan.slides)
    story_count = sum(slide.slide_type in _STORY_SLIDE_TYPES for slide in plan.slides)
    exploration_count = sum(
        slide.slide_type in _EXPLORATION_SLIDE_TYPES for slide in plan.slides
    )

    if game_count:
        weight = min(12, game_count * 3)
        scores["swift"] += weight
        reasons["swift"].append(f"game-slides:{game_count}+{weight}")
    if story_count:
        weight = min(8, story_count * 3)
        scores["modern"] += weight
        reasons["modern"].append(f"story-slides:{story_count}+{weight}")
    if exploration_count and domain in {"science", "math"}:
        weight = min(6, exploration_count)
        scores["dynamic"] += weight
        reasons["dynamic"].append(
            f"exploration-slides:{exploration_count}+{weight}"
        )

    topic_text = "\n".join(
        [
            plan.meta.topic,
            instructions or "",
            *[goal for goal in plan.lesson_goals],
            *[slide.screen_content.title for slide in plan.slides],
        ]
    ).casefold()
    for template, terms in _TEMPLATE_TERMS.items():
        matched = [term for term in terms if term.casefold() in topic_text]
        if not matched:
            continue
        # Cap lexical routing so a long outline cannot overwhelm the structural
        # domain/slide signals. Topic vocabulary is supporting evidence, not truth.
        weight = min(8, len(matched) * 2)
        scores[template] += weight
        reasons[template].append(
            f"terms:{','.join(matched[:4])}+{weight}"
        )

    best_score = max(scores.values()) if scores else 0
    if best_score <= 0:
        return KindergartenTemplateRoutingDecision(
            template=KINDERGARTEN_TEMPLATE_FALLBACK,
            reason="fallback:no-routing-signal",
            scores=scores,
        )

    selected = min(
        (name for name, score in scores.items() if score == best_score),
        key=lambda name: (_TEMPLATE_PRIORITY[name], name),
    )
    reason_parts = reasons[selected] or ["highest-routing-score"]
    return KindergartenTemplateRoutingDecision(
        template=selected,
        reason=";".join(reason_parts),
        scores=scores,
    )
