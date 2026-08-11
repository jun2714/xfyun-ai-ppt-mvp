from utils.llm_calls.generate_slide_content import _prepare_response_schema


def _schema():
    return {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "minLength": 1,
                "maxLength": 46,
                "x-cjk-max-length": 9,
            }
        },
        "required": ["title"],
    }


def test_chinese_schema_uses_geometry_based_capacity():
    response = _prepare_response_schema(_schema(), "Chinese")
    assert response["properties"]["title"]["maxLength"] == 9
    assert "x-cjk-max-length" not in response["properties"]["title"]


def test_english_schema_keeps_original_capacity_and_removes_extension():
    response = _prepare_response_schema(_schema(), "English")
    assert response["properties"]["title"]["maxLength"] == 46
    assert "x-cjk-max-length" not in response["properties"]["title"]
