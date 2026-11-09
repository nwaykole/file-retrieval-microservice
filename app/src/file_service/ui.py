"""Minimal browser UI: a login form and the customer's file list at /login.

The page is static. Its script reads data only from the JSON API (/auth/*, /v1/files) and
writes it with textContent, so stored filenames can't inject HTML. A strict
Content-Security-Policy allows only this origin's own script and stylesheet: no inline
code, no third-party resources, no framing.
"""
from __future__ import annotations

from importlib.resources import files

from fastapi import APIRouter, Response

_STATIC = files("file_service") / "static"
_MEDIA_TYPES = {
    "login.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
}
_CONTENT = {name: (_STATIC / name).read_bytes() for name in _MEDIA_TYPES}   # read once at import

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)
_HEADERS = {
    "content-security-policy": CONTENT_SECURITY_POLICY,
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}

router = APIRouter(include_in_schema=False)


def _serve(name: str) -> Response:
    return Response(_CONTENT[name], media_type=_MEDIA_TYPES[name], headers=_HEADERS)


@router.get("/login")
async def login_page() -> Response:
    return _serve("login.html")


@router.get("/ui/app.js")
async def app_js() -> Response:
    return _serve("app.js")


@router.get("/ui/app.css")
async def app_css() -> Response:
    return _serve("app.css")
