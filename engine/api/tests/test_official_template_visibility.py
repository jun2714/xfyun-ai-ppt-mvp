import uuid
from types import SimpleNamespace

from services.owner_scope import is_template_visible_to, mark_template_official


def test_teacher_can_see_official_template_owned_by_admin():
    teacher = uuid.uuid4()
    admin = uuid.uuid4()
    official = SimpleNamespace(is_default=True, owner_id=admin)
    private = SimpleNamespace(is_default=False, owner_id=admin)

    assert is_template_visible_to(official, teacher)
    assert not is_template_visible_to(private, teacher)
    assert is_template_visible_to(private, admin)


def test_unowned_official_template_is_visible_to_any_teacher():
    teacher = uuid.uuid4()
    official = SimpleNamespace(is_default=True, owner_id=None)
    assert is_template_visible_to(official, teacher)
    assert is_template_visible_to(official, None)


def test_admin_upload_is_marked_shared_official():
    admin = uuid.uuid4()
    template = mark_template_official(
        SimpleNamespace(is_default=False, owner_id=admin),
        is_admin=True,
    )
    assert template.is_default is True
    assert template.owner_id is None


def test_teacher_upload_stays_private():
    teacher = uuid.uuid4()
    template = mark_template_official(
        SimpleNamespace(is_default=False, owner_id=teacher),
        is_admin=False,
    )
    assert template.is_default is False
    assert template.owner_id == teacher
