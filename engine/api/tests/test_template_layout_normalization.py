from templates.v2.generation import _normalize_slide_layout_payload, _parse_json_content


def test_normalizes_common_model_schema_drift():
    payload = {
        "id": "title_cards",
        "description": "A title with a reusable row of cards.",
        "components": [
            {
                "id": "cards",
                "description": "Reusable cards",
                "position": {"x": 0, "y": 0},
                "elements": [
                    {
                        "type": "grid",
                        "name": "cards_grid",
                        "columns": 2,
                        "justify_items": "start",
                        "children": [
                            {
                                "direction": "row",
                                "name": "card",
                                "justify_content": "space-between",
                                "children": [],
                            }
                        ],
                    }
                ],
            },
            "model commentary that must not become a component",
        ],
    }

    normalized = _normalize_slide_layout_payload(payload)
    grid = normalized["components"][0]["elements"][0]
    card = grid["children"][0]

    assert len(normalized["components"]) == 1
    assert grid["justify_items"] == "flex-start"
    assert grid["min_children"] == grid["max_children"] == 1
    assert card["type"] == "flex"
    assert card["justify_content"] == "stretch"
    assert card["min_children"] == card["max_children"] == 0


def test_parses_first_json_object_when_provider_appends_commentary():
    parsed = _parse_json_content('{"id":"layout"}\nGenerated successfully.')

    assert parsed == {"id": "layout"}


def test_parses_fenced_json_with_trailing_commentary():
    parsed = _parse_json_content('```json\n{"id":"layout"}\n```\nLooks good.')

    assert parsed == {"id": "layout"}


def test_parses_openai_compatible_dict_text_parts():
    parsed = _parse_json_content(
        [{"type": "text", "text": '{"id":"layout"}'}]
    )

    assert parsed == {"id": "layout"}
