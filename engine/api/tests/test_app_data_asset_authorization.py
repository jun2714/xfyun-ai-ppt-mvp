import uuid

from api.v1.auth.assets import is_app_data_path_authorized


def test_owner_can_read_current_and_direct_legacy_image_paths():
    owner = uuid.UUID("d8d62efc-2ad0-420d-b837-7cf82e9cec5d")

    assert is_app_data_path_authorized(
        f"/app_data/images/users/{owner}/new.png",
        user_id=owner,
        is_admin=False,
    )
    assert is_app_data_path_authorized(
        f"/app_data/images/{owner}/legacy.png?tn_session=secret",
        user_id=owner,
        is_admin=False,
    )


def test_owner_cannot_read_another_users_direct_legacy_image_path():
    owner = uuid.uuid4()
    other = uuid.uuid4()

    assert not is_app_data_path_authorized(
        f"/app_data/images/{other}/private.png",
        user_id=owner,
        is_admin=False,
    )
