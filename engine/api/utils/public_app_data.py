PUBLIC_APP_DATA_PREFIXES = (
    "/app_data/fonts/",
    "/app_data/templates/",
)
PUBLIC_PREVIEW_ROOTS = (
    "/app_data/library/",
    "/app_data/presentations/",
)
PUBLIC_PREVIEW_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def is_public_app_data_preview(path: str) -> bool:
    """True for slide preview images that <img> tags must load without Authorization."""
    lowered = (path or "").split("?", 1)[0].lower()
    if any(lowered.startswith(prefix) for prefix in PUBLIC_APP_DATA_PREFIXES):
        return True
    if not any(lowered.startswith(root) for root in PUBLIC_PREVIEW_ROOTS):
        return False
    return lowered.endswith(PUBLIC_PREVIEW_SUFFIXES)
