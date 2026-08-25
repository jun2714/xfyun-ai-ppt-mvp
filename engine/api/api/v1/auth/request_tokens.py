from fastapi import Request

from api.v1.auth.config import SESSION_COOKIE_NAME


def collect_request_session_tokens(request: Request) -> list[tuple[str, str]]:
    """Return auth tokens in TeachNova-safe order: explicit credentials beat cookies.

    A leftover ``presenton_session`` cookie from the admin account was previously
    checked first, so every teacher iframe inherited admin's 我的项目 and wrote
    new decks into the admin workspace.
    """
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(source: str, token: str) -> None:
        value = (token or "").strip()
        if not value or value in seen:
            return
        seen.add(value)
        ordered.append((source, value))

    authorization = request.headers.get("Authorization") or ""
    if authorization.lower().startswith("bearer "):
        add("bearer", authorization.split(" ", 1)[1])

    add(
        "query",
        request.query_params.get("tn_session") or request.query_params.get("session") or "",
    )
    add("cookie", request.cookies.get(SESSION_COOKIE_NAME) or "")
    return ordered
