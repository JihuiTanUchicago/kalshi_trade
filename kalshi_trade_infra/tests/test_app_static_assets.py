"""Local fonts use the same restricted, immutable static asset path as CSS."""
import io
import re

import pytest

from app import server


def static_response(path):
    handler = object.__new__(server.Handler)
    handler.wfile = io.BytesIO()
    headers = []
    handler._headers = lambda *args: headers.append(args)
    handler._send_static(path)
    return headers[0], handler.wfile.getvalue()


def test_bundled_font_is_served_with_font_mime_and_immutable_cache():
    css = (server.STATIC_DIR / 'app.css').read_text()
    name = re.search(r'url\("(dm-sans-latin-[a-f0-9]+\.woff2)"\)', css).group(1)
    headers, body = static_response('/static/' + name)
    assert headers[:3] == (200, 'font/woff2', len(body))
    assert body == (server.STATIC_DIR / name).read_bytes()
    assert body.startswith(b'wOF2')
    assert ('Cache-Control', 'public, max-age=31536000, immutable') in headers[3]
    assert "font-src 'self'" in server.CSP


@pytest.mark.parametrize('path', [
    '/static/missing.woff2', '/static/../dm-sans.woff2',
    '/static/%2e%2e/dm-sans.woff2', '/static/DM-Sans-OFL.txt',
    '/static/subdirectory/font.woff2',
])
def test_font_support_keeps_missing_files_and_non_assets_inaccessible(path):
    headers, body = static_response(path)
    assert headers[0] == 404
    assert body == b'Not found'
