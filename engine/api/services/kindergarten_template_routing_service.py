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

# The current bundled dynamic pack renders as a dark black/orange business deck
# despite its legacy routing metadata claiming a bright child-friendly style.
# Keep manual selection available, but never auto-route preschool lessons to it
# until that visual pack is replaced or re-audited.
_AUTO_EXCLUDED_TEMPLATES = {"dynamic"}

_DOMAIN_WEIGHTS: dict[str, dict[str, int]] = {
    "science": {"dynamic": 9, "standard": 9},
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
    allow_classroom: bool = True,
    content_mode: str = "classroom",
    topic: str | None = None,
    available_templates: dict | None = None,
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

    content_slides = [slide for slide in plan.slides if slide.slide_type != "cover-scene"]
    if allow_classroom and content_slides and (
        content_mode == "training"
        or all(any(asset.required for asset in slide.assets) for slide in content_slides)
    ):
        return _resolve_education_pack(plan, content_mode, instructions, topic, available_templates)

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

    eligible_templates = [
        name for name in _TEMPLATE_PRIORITY if name not in _AUTO_EXCLUDED_TEMPLATES
    ]
    best_score = max((scores[name] for name in eligible_templates), default=0)
    if best_score <= 0:
        return KindergartenTemplateRoutingDecision(
            template=KINDERGARTEN_TEMPLATE_FALLBACK,
            reason="fallback:no-routing-signal",
            scores=scores,
        )

    selected = min(
        (name for name in eligible_templates if scores[name] == best_score),
        key=lambda name: (_TEMPLATE_PRIORITY[name], name),
    )
    reason_parts = reasons[selected] or ["highest-routing-score"]
    return KindergartenTemplateRoutingDecision(
        template=selected,
        reason=";".join(reason_parts),
        scores=scores,
    )


def _resolve_education_pack(plan, content_mode, instructions, topic, available_templates):
    """Rank only the correct audience, then preflight every page without an LLM.

    Topic words support the declared purpose and planned activity structure.
    Capacity can reject a top-ranked pack; reviewed copy is never rewritten.
    """
    from templates.education_variants import build_education_variant
    from templates.kindergarten_classroom import build_classroom_template
    from templates.teacher_training import build_training_template
    from templates.education_catalog import EDUCATION_PACKS, INTERACTIVE_PACK_IDS, build_education_pack
    from templates.v2.schema import get_template_schema
    from models.presentation_layout import PresentationLayoutModel, SlideLayoutModel
    from utils.layout_compatibility import LayoutCompatibilityError, get_allowed_layout_indices_for_outline

    teacher = content_mode == "training"
    fallback = "teacher-training" if teacher else "kindergarten-classroom"
    keys = ["training-case", "training-action"] if teacher else ["classroom-nature", "classroom-story"]
    scores = {key: 0 for key in keys}
    scores[fallback] = 1
    reasons = {fallback: "采用通用教研版式" if teacher else "采用通用课堂版式"}
    text = "\n".join([topic or plan.meta.topic, instructions or "", *plan.lesson_goals,
                      *[s.screen_content.title for s in plan.slides]])
    if teacher:
        terms = {
            "training-case": ("案例", "观察记录", "证据", "原话", "对照", "分析", "研讨"),
            "training-action": ("实施", "行动计划", "改进计划", "复盘", "负责人", "落实", "跟进", "步骤"),
        }
        reasons.update({"training-case": "教师教研包含案例或观察证据，推荐案例档案版式",
                        "training-action": "教师教研侧重实施与复盘，推荐步骤路线图版式"})
    else:
        terms = {"classroom-nature": ("植物", "种子", "天气", "动物", "自然", "科学", "实验"),
                 "classroom-story": ("绘本", "故事", "阅读", "讲述", "情绪", "角色")}
        domain = plan.meta.domain
        if domain == "science":
            scores["classroom-nature"] += 10
        elif domain == "language":
            scores["classroom-story"] += 10
        scores["classroom-nature"] += min(6, sum(s.slide_type in {"image-observation", "compare"} for s in plan.slides) * 2)
        scores["classroom-story"] += min(6, sum(s.slide_type == "story-intro" for s in plan.slides) * 3)
        reasons.update({"classroom-nature": "课堂以科学探索和观察比较为主，推荐观察手册版式",
                        "classroom-story": "课堂以阅读讲述或情绪表达为主，推荐绘本分镜版式"})
    for key, words in terms.items():
        scores[key] += min(8, sum(word in text for word in words) * 2)
    # New packs declare their routing signals in the catalog. Topic/interaction
    # evidence is required; age/domain alone must not turn a lesson into a game.
    for key in INTERACTIVE_PACK_IDS:
        spec = EDUCATION_PACKS[key]
        if spec.audience != ("teacher" if teacher else "child"):
            continue
        matched = [word for word in spec.keywords if word in text]
        actions = sum(slide.interaction.type in spec.interactions for slide in plan.slides)
        score = min(18, len(matched) * 6) + min(12, actions * 3)
        signals = []
        if matched:
            signals.append("主题包含" + "、".join(matched[:3]))
        if actions:
            signals.append(f"含 {actions} 个参与活动")
        if score:
            if plan.meta.domain in spec.domains:
                score += 4
                signals.append("教学领域适合")
            if plan.meta.age_group in spec.age_groups:
                score += 1
        scores[key] = score
        reasons[key] = ("推荐教研工作坊" if teacher else "推荐游戏探索") + (
            "：" + "；".join(signals) if signals else "；作为同用途容量备选")
    # No strong signal: retain a neutral audience-appropriate pack.
    eligible = list(scores)
    if available_templates is not None:
        audience = "teacher" if teacher else "child"
        eligible = []
        for key in scores:
            template = available_templates.get(key)
            if template is None:
                continue
            metadata = (template.assets or {}).get("template_metadata", {})
            if metadata.get("auto_match") is False:
                continue
            if metadata.get("audiences") and audience not in metadata["audiences"]:
                continue
            eligible.append(key)
        if not eligible:
            return KindergartenTemplateRoutingDecision(
                template="", reason="当前没有可自动匹配的教研模板，请手动选择可用模板。" if teacher else
                "当前没有可自动匹配的课堂模板，请手动选择可用模板。", scores={},
            )
    ranked = sorted(eligible, key=lambda key: -scores[key])
    outline = plan.to_presentation_outline()
    failures = []
    for key in ranked:
        template = available_templates[key] if available_templates is not None else build_education_pack(key)
        schemas = get_template_schema(template.layouts)["layouts"]
        layout = PresentationLayoutModel(name=key, slides=[
            SlideLayoutModel(id=entry["layout_id"], json_schema=entry["schema"]) for entry in schemas
        ])
        try:
            get_allowed_layout_indices_for_outline(outline, layout)
        except LayoutCompatibilityError as error:
            failures.append(error)
            continue
        reason = reasons[key]
        if failures:
            reason += "；优先模板的正文容量不足，已改用可完整保留文案的同用途模板"
        return KindergartenTemplateRoutingDecision(template=key, reason=reason, scores=scores)
    # Preserve a reviewable outline even if no pack fits. Preparation still
    # blocks overflowing pages; do not discard a paid plan or silently split it.
    key = ranked[0]
    return KindergartenTemplateRoutingDecision(
        template=key,
        reason=f"{reasons[key]}；现有模板无法完整容纳文案，请先调整大纲。{failures[0]}",
        scores=scores,
    )
