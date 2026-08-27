from utils.llm_calls.generate_slide_content import (
    _prepare_response_schema,
    get_user_prompt,
)


def test_slide_prompt_carries_hidden_asset_and_answer_contract():
    prompt = get_user_prompt(
        "猜猜是谁？\n- 谁有长长的耳朵？",
        "Chinese",
        slide_number=2,
        content_contract={
            "relationship": "question",
            "activity_id": "animal-ears-1",
            "answer_key": "B",
            "required_asset_semantics": ["小兔子的两只长耳朵"],
        },
    )

    assert "# MACHINE CONTENT CONTRACT: START" in prompt
    assert '"answer_key":"B"' in prompt
    assert "小兔子的两只长耳朵" in prompt


def test_speaker_notes_do_not_require_100_characters_of_filler():
    schema = _prepare_response_schema(
        {
            "type": "object",
            "properties": {
                "title": {"type": "string", "maxLength": 20},
            },
            "required": ["title"],
        },
        "Chinese",
    )

    assert schema is not None
    speaker_note = schema["properties"]["__speaker_note__"]
    assert speaker_note["minLength"] == 20
