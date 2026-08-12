import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

_TEMP_DIR = tempfile.mkdtemp(prefix="teachnova-test-")
os.environ["APP_DATA_DIRECTORY"] = _TEMP_DIR
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TEMP_DIR, 'fastapi.db').as_posix()}"

from api.v1.ppt.endpoints.presentation import _apply_template_content_to_ui


ROOT = Path(__file__).resolve().parents[3]
GENERAL_TEMPLATE = ROOT / "templates" / "general" / "template.json"


class TemplateContentApplyTests(unittest.TestCase):
    def test_general_feature_cards_replace_english_placeholders(self):
        template = json.loads(GENERAL_TEMPLATE.read_text(encoding="utf-8"))
        layout = next(
            item
            for item in template["layouts"]
            if item.get("id") == "title_image_bullet_points_1"
        )
        ui = {
            "id": layout["id"],
            "name": layout.get("name"),
            "description": layout.get("description"),
            "components": copy.deepcopy(layout["components"]),
        }
        content = {
            "large_title_area": {"基础通用": "海龟——慢吞吞的旅行"},
            "feature_grid_area": {
                "基础通用": [
                    {
                        "基础通用": {"icon_query": "turtle shell"},
                        "基础通用_2": "厚厚的壳",
                        "基础通用_3": "海龟背着硬壳慢慢爬，保护自己不受伤害。",
                    },
                    {
                        "基础通用": {"icon_query": "ocean swim"},
                        "基础通用_2": "会游泳",
                        "基础通用_3": "它用宽宽的鳍在海里划水，像在跳舞。",
                    },
                    {
                        "基础通用": {"icon_query": "sea plants"},
                        "基础通用_2": "吃海草",
                        "基础通用_3": "海龟喜欢啃海草，把海洋当餐厅。",
                    },
                ]
            },
            "right_image_panel": {
                "基础通用": {"image_prompt": "cute cartoon sea turtle underwater"}
            },
        }

        hydrated = _apply_template_content_to_ui(ui, content)
        feature_grid = next(
            component
            for component in hydrated["components"]
            if component.get("id") == "feature_grid_area"
        )
        cards = feature_grid["elements"][0]["children"]

        texts = []
        for card in cards[:3]:
            card_texts = [
                "".join(run.get("text", "") for run in (child.get("runs") or []))
                for child in card["children"]
                if child.get("type") == "text"
            ]
            texts.append(card_texts)

        self.assertEqual(
            texts,
            [
                ["厚厚的壳", "海龟背着硬壳慢慢爬，保护自己不受伤害。"],
                ["会游泳", "它用宽宽的鳍在海里划水，像在跳舞。"],
                ["吃海草", "海龟喜欢啃海草，把海洋当餐厅。"],
            ],
        )
        joined = "\n".join(text for card in texts for text in card)
        self.assertNotIn("Custom Software", joined)
        self.assertNotIn("Digital Consulting", joined)
        self.assertNotIn("Support Services", joined)


if __name__ == "__main__":
    unittest.main()
