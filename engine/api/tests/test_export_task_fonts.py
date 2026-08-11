from services import export_task_service


def test_localizes_app_font_without_internal_http_request(monkeypatch, tmp_path):
    font_path = tmp_path / "classroom.ttf"
    font_path.write_bytes(b"font-bytes")
    monkeypatch.setattr(
        export_task_service,
        "resolve_app_path_to_filesystem",
        lambda path: str(font_path) if path == "/app_data/fonts/classroom.ttf" else None,
    )

    localized = export_task_service._localize_json_fonts(
        {
            "Classroom": "http://127.0.0.1:8000/app_data/fonts/classroom.ttf",
            "Remote": "https://fonts.example.com/remote.woff2",
        }
    )

    assert localized["Classroom"].startswith("data:font/ttf;base64,")
    assert localized["Remote"] == "https://fonts.example.com/remote.woff2"
