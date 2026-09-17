"""Single registration point for code-owned, editable education packs.

Candidate means code-validated only; it must not be presented as classroom-approved.
Factories are imported lazily so schema generation and routing share this catalog.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class EducationPackSpec:
    id: str
    audience: str
    domains: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    interactions: tuple[str, ...] = ()
    age_groups: tuple[str, ...] = ()
    schema_version: int = 1


EDUCATION_PACKS = {
    spec.id: spec for spec in (
        EducationPackSpec("kindergarten-classroom", "child"),
        EducationPackSpec("teacher-training", "teacher"),
        EducationPackSpec("classroom-nature", "child", ("science",)),
        EducationPackSpec("classroom-story", "child", ("language",)),
        EducationPackSpec("training-case", "teacher"),
        EducationPackSpec("training-action", "teacher"),
        EducationPackSpec("classroom-game", "child", ("math", "health", "social"),
                          ("游戏", "闯关", "猜猜", "找不同", "分类", "排序", "选择"),
                          ("choose", "guess", "match", "classify", "sequence", "imitate"),
                          ("3-4岁", "4-5岁", "5-6岁", "小班", "中班", "大班")),
        EducationPackSpec("training-workshop", "teacher", (),
                          ("工作坊", "小组讨论", "分组研讨", "同伴互评", "共创", "策略比较"),
                          ("discuss",), ("教师教研",)),
    )
}

INTERACTIVE_PACK_IDS = ("classroom-game", "training-workshop")


def education_pack_audience(template_id):
    spec = EDUCATION_PACKS.get(template_id)
    return spec.audience if spec else None


def build_education_pack(template_id):
    from templates.kindergarten_classroom import build_classroom_template
    from templates.teacher_training import build_training_template
    from templates.education_variants import build_education_variant
    from templates.teaching_activity import build_activity_template

    spec = EDUCATION_PACKS[template_id]
    if template_id == "kindergarten-classroom":
        template = build_classroom_template()
    elif template_id == "teacher-training":
        template = build_training_template()
    elif template_id in INTERACTIVE_PACK_IDS:
        template = build_activity_template(template_id)
    else:
        template = build_education_variant(template_id)
    assets = dict(template.assets or {})
    metadata = dict(assets.get("template_metadata") or {})
    metadata.update(pack_schema_version=spec.schema_version, audiences=[spec.audience],
                    domains=list(spec.domains), age_groups=list(spec.age_groups),
                    interaction_types=list(spec.interactions), editable_text=True,
                    interaction_delivery="teacher-led-slides", quality_status="candidate")
    assets["template_metadata"] = metadata
    template.assets = assets
    return template
