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


def test_omitted_generated_slot_clears_imported_lorem_ipsum_copy():
    ui = {
        "components": [
            {
                "id": "unused_card",
                "position": {"x": 100, "y": 100},
                "elements": [
                    {
                        "type": "text",
                        "decorative": False,
                        "name": "body",
                        "position": {"x": 0, "y": 0},
                        "size": {"width": 300, "height": 100},
                        "font": {"size": 24, "line_height": 1.2},
                        "runs": [
                            {
                                "text": "Lorem ipsum dolor sit amet, consectetur adipiscing elit"
                            }
                        ],
                    }
                ],
            }
        ]
    }

    result = _apply_template_content_to_ui(ui, {"unused_card": {}})

    assert result["components"][0]["elements"][0]["runs"] == []


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


def test_wrapped_card_label_borrows_spare_height_from_description():
    ui = {
        "components": [
            {
                "id": "card",
                "position": {"x": 150, "y": 470},
                "elements": [
                    {
                        "type": "text",
                        "decorative": False,
                        "name": "label",
                        "position": {"x": 0, "y": 0},
                        "size": {"width": 229.52, "height": 28},
                        "font": {"size": 18.6, "line_height": 1.4},
                        "runs": [{"text": "Label"}],
                    },
                    {
                        "type": "text",
                        "decorative": False,
                        "name": "description",
                        "position": {"x": 0, "y": 35.09},
                        "size": {"width": 232.15, "height": 144.5},
                        "font": {"size": 17.78, "line_height": 1.5},
                        "runs": [{"text": "Description"}],
                    },
                ],
            }
        ]
    }
    content = {
        "card": {
            "label": "它先钻出圆圆的头，再伸出两片小叶子。",
            "description": "小芽说：谢谢你们帮我找到水和阳光。",
        }
    }

    result = _apply_template_content_to_ui(ui, content)
    label, description = result["components"][0]["elements"]

    assert label["font"]["size"] == 14
    assert label["size"]["height"] >= 40
    assert description["position"]["y"] > 35.09
    assert description["size"]["height"] < 144.5
    assert abs(
        description["position"]["y"]
        + description["size"]["height"]
        - (35.09 + 144.5)
    ) < 1e-6
