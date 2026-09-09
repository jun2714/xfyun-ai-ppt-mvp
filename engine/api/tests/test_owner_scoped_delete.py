import asyncio
import uuid
from types import SimpleNamespace

from api.v1.auth.context import reset_current_owner_id, set_current_owner_id
from services.owner_scope import get_owned_by_id, is_row_owned_by


def test_owner_compare_ignores_uuid_hyphens():
    owner = uuid.UUID("d8d62efc-2ad0-420d-b837-7cf82e9cec5d")
    row = SimpleNamespace(owner_id="d8d62efc2ad0420db8377cf82e9cec5d")
    assert is_row_owned_by(row, owner)
    assert not is_row_owned_by(row, uuid.uuid4())
    assert not is_row_owned_by(SimpleNamespace(owner_id=None), owner)
    assert not is_row_owned_by(None, owner)


def test_get_owned_by_id_finds_row_without_session_get(monkeypatch):
    owner = uuid.UUID("d8d62efc-2ad0-420d-b837-7cf82e9cec5d")
    presentation_id = uuid.uuid4()
    owned = SimpleNamespace(id=presentation_id, owner_id=owner)
    foreign = SimpleNamespace(id=presentation_id, owner_id=uuid.uuid4())
    token = set_current_owner_id(owner)
    try:
        async def _return_owned(_session, _model, _row_id):
            return owned

        monkeypatch.setattr("services.owner_scope.get_by_id_unscoped", _return_owned)
        assert asyncio.run(get_owned_by_id(object(), object, presentation_id)) is owned

        async def _return_foreign(_session, _model, _row_id):
            return foreign

        monkeypatch.setattr("services.owner_scope.get_by_id_unscoped", _return_foreign)
        assert asyncio.run(get_owned_by_id(object(), object, presentation_id)) is None
    finally:
        reset_current_owner_id(token)
