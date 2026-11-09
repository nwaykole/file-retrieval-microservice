"""Browser login page: served with the right types and a strict Content-Security-Policy."""
import pytest


def test_login_page_is_public_html_with_strict_csp(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="login-form"' in response.text
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize(("path", "media_type"), [
    ("/ui/app.js", "text/javascript"),
    ("/ui/app.css", "text/css"),
])
def test_assets_are_served(client, path, media_type):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media_type)
    assert response.headers["x-content-type-options"] == "nosniff"


def test_script_never_writes_server_data_as_html(client):
    script = client.get("/ui/app.js").text
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in script


def test_page_has_no_inline_script_or_style(client):
    page = client.get("/login").text
    assert "<script>" not in page          # only <script src=...>, which the CSP allows
    assert "<style" not in page and "style=" not in page
