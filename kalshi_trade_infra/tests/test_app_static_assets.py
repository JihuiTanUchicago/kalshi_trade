"""Local fonts use the same restricted, immutable static asset path as CSS."""
import io

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
    # The default UI loads Rubik externally; this font remains a shipped static asset.
    name = 'dm-sans-latin-9fea608a94.woff2'
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


def test_broker_assets_are_versioned_and_loaded_before_app_boot():
    headers, body = static_response('/settings/account')
    html = body.decode()
    assert headers[0] == 200
    versions = server._static_versions()
    assert '/static/broker-connections.js?v=' + versions['broker-connections.js'] in html
    assert '/static/broker-connections.css?v=' + versions['broker-connections.css'] in html
    assert '{{brokers_' not in html
    assert html.index('/static/broker-connections.js') < html.index('/static/boot.js')
    asset_headers, js = static_response('/static/broker-connections.js')
    assert asset_headers[0] == 200 and b'TauBrokerConnections' in js
