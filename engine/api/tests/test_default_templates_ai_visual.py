import asyncio

from templates import default_templates


class _FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0

    async def get(self, _model, _template_id):
        return None

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_startup_imports_internal_ai_visual_template_without_disk_template(tmp_path, monkeypatch):
    session = _FakeSession()

    monkeypatch.setattr(
        default_templates,
        "async_session_maker",
        lambda: _FakeSessionContext(session),
    )

    async def ignore_stale(*_args, **_kwargs):
        return None

    monkeypatch.setattr(default_templates, "_remove_stale_default_templates", ignore_stale)
    monkeypatch.setattr(default_templates, "_load_disabled_bundled_template_ids", lambda: set())

    asyncio.run(default_templates.import_default_templates_on_startup(tmp_path))

    ids = [template.id for template in session.added]
    assert ids == ["ai-visual"]
    assert session.added[0].assets["template_metadata"]["internal_visual_mode"] == "ai-background"
    assert session.commits == 1
