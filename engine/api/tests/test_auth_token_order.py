from starlette.requests import Request

from api.v1.auth.request_tokens import collect_request_session_tokens


def _request(*, authorization="", cookie="", query_string=b"") -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": query_string,
            "headers": headers,
            "client": ("127.0.0.1", 8000),
            "server": ("127.0.0.1", 8000),
        }
    )


def test_bearer_wins_over_admin_cookie():
    tokens = collect_request_session_tokens(
        _request(
            authorization="Bearer teacher-token",
            cookie="presenton_session=admin-cookie",
        )
    )
    assert tokens[0] == ("bearer", "teacher-token")
    assert tokens[-1] == ("cookie", "admin-cookie")


def test_tn_session_wins_over_cookie():
    tokens = collect_request_session_tokens(
        _request(
            cookie="presenton_session=admin-cookie",
            query_string=b"tn_session=teacher-token",
        )
    )
    assert tokens[0] == ("query", "teacher-token")
