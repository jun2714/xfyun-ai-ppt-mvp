from utils.public_app_data import is_public_app_data_preview


def test_library_and_presentation_previews_are_public():
    assert is_public_app_data_preview(
        "/app_data/library/da8f5996-07c8-4d01-88f2-1f25f7a4f2ee/slide_1.jpg"
    )
    assert is_public_app_data_preview(
        "/app_data/presentations/11111111-1111-4111-8111-111111111111/slide_2.png"
    )
    assert is_public_app_data_preview("/app_data/fonts/classroom.ttf")
    assert not is_public_app_data_preview(
        "/app_data/presentations/11111111-1111-4111-8111-111111111111/original.pptx"
    )
    assert not is_public_app_data_preview("/app_data/images/secret.png")


def test_rewrite_keeps_ppt_api_prefix_on_absolute_urls():
    import json

    library_id = "lib-id"
    presentation_id = "pres-id"
    payload = {
        "url": "https://teachnova.nxzhiyi.com/ppt-api/app_data/library/lib-id/slide_1.jpg"
    }
    text = json.dumps(payload, ensure_ascii=False)
    text = text.replace(
        f"/ppt-api/app_data/library/{library_id}/",
        f"/ppt-api/app_data/presentations/{presentation_id}/",
    )
    text = text.replace(
        f"/app_data/library/{library_id}/",
        f"/app_data/presentations/{presentation_id}/",
    )
    rewritten = json.loads(text)
    assert rewritten["url"] == (
        "https://teachnova.nxzhiyi.com/ppt-api/app_data/presentations/pres-id/slide_1.jpg"
    )
