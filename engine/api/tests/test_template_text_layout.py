from api.v1.ppt.endpoints.presentation import (
    _apply_template_content_to_ui,
    _apply_template_text_content,
)


def test_explicit_empty_text_clears_imported_placeholder_copy():
    element = {
        "type": "text",
        "decorative": False,
        "name": "body",
        "size": {"width": 300, "height": 100},
        "font": {"size": 24, "line_height": 1.2},
        "runs": [{"text": "Lorem ipsum placeholder"}],
    }

    result = _apply_template_text_content(element, "")

    assert result["runs"] == []


def test_lone_heading_uses_vertical_gap_before_font_fitting():
    ui = {
        "components": [
            {
                "id": "heading",
                "position": {"x": 60, "y": 60},
                "elements": [
                    {
                        "type": "text",
                        "decorative": False,
                        "name": "title",
                        "position": {"x": 0, "y": 0},
                        "size": {"width": 1000, "height": 46},
                        "font": {"size": 60, "line_height": 1.25},
                        "runs": [{"text": "Heading"}],
                    }
                ],
            },
            {
                "id": "media",
                "position": {"x": 60, "y": 252},
                "elements": [{"type": "image", "decorative": True}],
            },
        ]
    }
    content = {
        "heading": {
            "title": "第一行\n第二行\n第三行\n第四行\n第五行",
        }
    }

    result = _apply_template_content_to_ui(ui, content)
    heading = result["components"][0]["elements"][0]

    assert heading["size"]["height"] == 176
    assert 20 <= heading["font"]["size"] < 60
    assert "第五行" in heading["runs"][0]["text"]
