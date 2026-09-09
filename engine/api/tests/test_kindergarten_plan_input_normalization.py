import jsonschema
import pytest
from pydantic import ValidationError

from models.kindergarten_lesson_plan import (
    KindergartenSlidePlan, LessonGameSpec, LessonInteraction,
)


@pytest.mark.parametrize("alias", ["observation", "compare", "reveal"])
def test_observation_alias_is_valid_at_schema_boundary_and_stored_canonically(alias):
    raw = {"type": alias, "instruction": "观察画面，说出发现"}
    jsonschema.validate(raw, LessonInteraction.model_json_schema())
    result = LessonInteraction.model_validate(raw)
    assert result.type == "observe"
    assert result.instruction == raw["instruction"]


def test_observation_slide_alias_preserves_visible_copy():
    raw = {"slide_no": 1, "slide_type": "observation", "teaching_goal": "认识种子",
           "screen_content": {"title": "小种子是什么样", "points": ["摸一摸"]},
           "teacher_note": "邀请幼儿观察。"}
    jsonschema.validate(raw, KindergartenSlidePlan.model_json_schema())
    result = KindergartenSlidePlan.model_validate(raw)
    assert result.slide_type == "image-observation"
    assert result.screen_content.title == raw["screen_content"]["title"]
    assert result.screen_content.points == raw["screen_content"]["points"]


def test_null_optional_game_collections_do_not_reject_an_otherwise_valid_answer():
    raw = {"type": "guess", "activity_id": "seed", "answer_key": "B",
           "options": {"A": "石头", "B": "种子"}, "answer_map": None,
           "sequence_order": None}
    jsonschema.validate(raw, LessonGameSpec.model_json_schema())
    result = LessonGameSpec.model_validate(raw)
    assert result.answer_map == {} and result.sequence_order == []
    assert result.answer_key == "B" and result.options == raw["options"]


def test_unknown_actions_and_malformed_game_values_are_not_silently_downgraded():
    with pytest.raises(ValidationError):
        LessonInteraction(type="invented-action")
    with pytest.raises(ValidationError):
        LessonGameSpec(type="guess", activity_id="x", options=["a", "b"])
