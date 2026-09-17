"""Teacher-led interaction: never invent answers or alter reviewed visible copy."""
from services.classroom_content_mapping import screen_roles


ROLE_LABELS = {"observe": "观察发现", "compare": "对比观察", "choice": "做出选择",
               "sequence": "排列顺序", "question": "先想一想", "reveal": "揭晓发现",
               "recap": "回顾分享", "discuss": "交流研讨"}


def teaching_page_role(outline):
    contract = outline.content_contract
    if not contract or not contract.preserve_visible_copy:
        return None
    # A teacher's edited outline invalidates old interaction/answer semantics.
    if not screen_roles(outline)[3]:
        return None
    role = contract.classroom_role
    if role == "cover-scene":
        return None
    if role == "answer-reveal":
        return "reveal"
    if role in {"guess-partial", "guess-shadow", "memory-missing"}:
        return "question"
    if role == "sequence" or contract.interaction_type == "sequence":
        return "sequence"
    if role == "compare":
        return "compare"
    if role in {"recap", "ending-scene"} or contract.interaction_type == "recall":
        return "recap"
    if contract.interaction_type in {"choose", "classify", "match"}:
        return "choice"
    if contract.interaction_type == "discuss":
        return "discuss"
    return "observe"


def interaction_speaker_notes(outline):
    role = teaching_page_role(outline)
    if role is None:
        return ""
    guidance = {
        "observe": "先留出观察时间，再请参与者描述看到的特征。",
        "compare": "先分别观察，再指出差异并说明依据。",
        "choice": "先独立选择，再交流理由；依据本次活动的参考答案或判断标准核对。",
        "sequence": "先口头排列或使用实体卡片，再说明前后关系。",
        "question": "停留在本页收集猜想，暂不展示答案页。",
        "reveal": "与前面的猜想对照，说明答案依据。",
        "recap": "邀请参与者用自己的话回顾发现，联系本次目标。",
        "discuss": "先个人思考，再小组交流，区分观察事实与推断。",
    }
    contract = outline.content_contract
    lines = ["互动组织：" + guidance[role]]
    if contract.activity_id:
        lines.append("活动标识：" + contract.activity_id)
    if contract.answer_key:
        lines.append("教师参考答案：" + contract.game_options.get(contract.answer_key, contract.answer_key))
    if contract.game_sequence_order:
        lines.append("教师参考顺序：" + " → ".join(
            contract.game_options.get(key, key) for key in contract.game_sequence_order))
    if contract.game_answer_map:
        lines.append("教师参考对应：" + "；".join(
            f"{contract.game_options.get(key, key)} → {contract.game_options.get(value, value)}"
            for key, value in contract.game_answer_map.items()))
    return "\n".join(lines)
