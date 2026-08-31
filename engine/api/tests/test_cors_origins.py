import api.main as main_module


def _clear_env(monkeypatch):
    for key in (
        "NEXT_PUBLIC_URL",
        "NEXT_PUBLIC_FAST_API",
        "TEACHNOVA_CORS_ORIGINS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_cors_allows_local_editor_when_fastapi_is_loopback(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("NEXT_PUBLIC_URL", "https://ppt.teachnova.com")
    monkeypatch.setenv("NEXT_PUBLIC_FAST_API", "http://127.0.0.1:8000")
    monkeypatch.setenv("TEACHNOVA_CORS_ORIGINS", "http://127.0.0.1:3030")

    origins = main_module._cors_origins()

    assert "https://ppt.teachnova.com" in origins
    assert "http://127.0.0.1:3030" in origins
    assert "http://127.0.0.1:5001" in origins
    assert "http://localhost:5001" in origins
    assert "http://127.0.0.1:5173" in origins


def test_cors_does_not_expose_loopback_origins_in_production(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("NEXT_PUBLIC_URL", "https://ppt.teachnova.com")
    monkeypatch.setenv("NEXT_PUBLIC_FAST_API", "https://teachnova.com/ppt-api")
    monkeypatch.setenv("TEACHNOVA_CORS_ORIGINS", "https://teachnova.com")

    origins = main_module._cors_origins()

    assert origins == ["https://ppt.teachnova.com", "https://teachnova.com"]


def test_cors_keeps_wildcard_for_unconfigured_standalone_api(monkeypatch):
    _clear_env(monkeypatch)

    assert main_module._cors_origins() == ["*"]
