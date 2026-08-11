import asyncio
import os
import tempfile

# The engine's production default is a Linux path. Tests run directly on
# Windows, so configure a local data directory before importing the database
# dependency graph used by the auth module.
os.environ.setdefault(
    "APP_DATA_DIRECTORY",
    os.path.join(tempfile.gettempdir(), "sparkdeck-engine-tests"),
)

from starlette.requests import Request

from api.v1.auth import users


def test_disabled_auth_does_not_require_user_config(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "true")

    def fail_if_jwt_strategy_is_created():
        raise AssertionError("disabled auth must not create a JWT strategy")

    monkeypatch.setattr(users, "get_jwt_strategy", fail_if_jwt_strategy_is_created)
    request = Request({"type": "http", "headers": []})

    result = asyncio.run(users.read_user_from_cookie(request, object()))

    assert result is None
