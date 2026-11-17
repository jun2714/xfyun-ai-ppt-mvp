"""Page-purpose visual direction, shared by mapping and the provider boundary."""


def visual_representation(contract) -> str:
    def read(key, default=None):
        return contract.get(key, default) if isinstance(contract, dict) else getattr(contract, key, default)
    if read("visual_audience") == "teacher" or read("classroom_role") == "cover-scene":
        return "illustration"
    explicit = read("visual_representation", "auto")
    if explicit in {"realistic", "illustration"}:
        return explicit
    # Legacy decks lack a declared mode. Infer only from structured teaching intent,
    # never from a topic word appearing in an unrelated story or game.
    if read("teaching_domain") in {"science", "health"} and read("classroom_role") in {
        "knowledge-single", "image-observation", "compare",
    }:
        return "realistic"
    return "illustration"


REALISTIC_DIRECTION = (
    "AI生成的自然写实教学图，不是真实拍摄照片。呈现自然光、真实比例、真实体色与清楚的身体结构；"
    "不要卡通、绘本、拟人表情、人类手脚、舞台、灯串、贴纸边框或模板配色染色。"
    "只展示本页明确要求的观察对象、特征和动作，背景简单且符合真实生活环境。"
    "完整保留需要观察的部位；静态图不能假装证明连续运动，运动方向须由准确动作或原生教学标记说明。"
    "必须符合明确的物种/对象及其识别特征，不能用海水背景证明鱼属于海鱼，不能混用淡水与海洋物种。"
)


def observation_identity_issue(assets) -> str | None:
    # A decorative background need not repeat the framed subject's identity,
    # but making the only teaching image a background cannot bypass this check.
    targets = [asset for asset in assets if asset.role != "background"] or assets
    for asset in targets:
        subjects = asset.observation_subjects
        if not subjects:
            return "写实认知图缺少明确对象、生活环境和识别特征，不能只凭画风判断科学准确。"
        for subject in subjects:
            if subject.name.strip() in {"鱼", "小鱼", "海鱼", "银色海鱼", "银色鱼", "动物", "植物", "生物", "海洋动物"}:
                return "写实认知图的对象名过于笼统，请先选定适合本课环境的具体物种，再描述识别特征。"
    return None


def has_conflicting_card_scenes(assets) -> bool:
    """An identical scene cannot depict distinct card subjects independently.

    Repeating the same subject is allowed (for example, counting apples).
    Empty descriptions are handled by the ordinary asset validation.
    """
    scenes = {}
    for asset in assets:
        description = "".join((asset.description or "").split())
        if not description:
            continue
        subject = "".join(asset.semantic_label.split())
        if description in scenes and scenes[description] != subject:
            return True
        scenes[description] = subject
    return False
