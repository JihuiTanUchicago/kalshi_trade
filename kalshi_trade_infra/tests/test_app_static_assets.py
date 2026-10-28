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
    # Both shipped fonts (DM Sans, Rubik) are local static assets.
    name = 'dm-sans-latin-9fea608a94.woff2'
    headers, body = static_response('/static/' + name)
    assert headers[:3] == (200, 'font/woff2', len(body))
    assert body == (server.STATIC_DIR / name).read_bytes()
    assert body.startswith(b'wOF2')
    assert ('Cache-Control', 'public, max-age=31536000, immutable') in headers[3]
    assert "font-src 'self'" in server.CSP


def test_landing_font_is_self_hosted_with_no_render_blocking_third_party_css():
    name = 'rubik-latin-691cd1d9b4.woff2'
    headers, body = static_response('/static/' + name)
    assert headers[:2] == (200, 'font/woff2') and body.startswith(b'wOF2')
    for css in ('app.css', 'app.meridian.css'):
        assert '/static/' + name in (server.STATIC_DIR / css).read_text()
    html = (server.STATIC_DIR / 'index.html').read_text()
    assert 'fonts.googleapis.com' not in html and 'fonts.gstatic.com' not in html
    assert 'googleapis' not in server.CSP and 'gstatic' not in server.CSP


@pytest.mark.parametrize('path', [
    '/static/missing.woff2', '/static/../dm-sans.woff2',
    '/static/%2e%2e/dm-sans.woff2', '/static/DM-Sans-OFL.txt',
    '/static/subdirectory/font.woff2',
])
def test_font_support_keeps_missing_files_and_non_assets_inaccessible(path):
    headers, body = static_response(path)
    assert headers[0] == 404
    assert body == b'Not found'


@pytest.mark.parametrize('path', ['/nope', '/setting', '/strategies/abc'])
def test_an_address_with_no_page_says_so_on_a_page_with_a_way_home(path):
    # It read a bare "Not found" in plain text, unstyled, with no link back.
    headers, body = static_response(path)
    html = body.decode()
    assert headers[:2] == (404, 'text/html; charset=utf-8')
    assert '<h1>Page not found</h1>' in html and '<a class="btn" href="/">Go to Tau</a>' in html
    assert 'There’s no page at this address.' in html and "'" not in html
    assert '/static/app.css?v=' + server._static_versions()['app.css'] in html and '<script' not in html


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


@pytest.mark.parametrize('css', ['app.css', 'app.meridian.css'])
def test_the_off_screen_skip_link_never_asks_for_a_web_font(css):
    # Skip to content is in every first paint, off screen. Meridian's, set in DM Sans, fetched the 37 KB font on a
    # phone for text no one sees, on the landing and sign-in too, which never use it. Its type (its own
    # font-family, else body's) resolves to no @font-face family, in both themes.
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / 'app' / 'static' / css).read_text()
    faces = set(re.findall(r'@font-face\s*\{[^}]*font-family:\s*"([^"]+)"', src))
    assert faces
    root_at = src.index(':root {')
    root = dict(re.findall(r'(--[\w-]+):\s*([^;]+);', src[root_at:src.index('}', root_at)]))
    rule = re.search(r'(?m)^\.skip \{([^}]*)\}', src).group(1)
    font = re.search(r'font-family:\s*([^;]+)', rule)
    if font:
        family = font.group(1)
    else:
        body = re.search(r'(?m)^body \{([^}]*)\}', src).group(1)
        family = re.search(r'font(?:-family)?:\s*([^;]+)', body).group(1)
    family = re.sub(r'var\((--[\w-]+)\)', lambda m: root.get(m.group(1), m.group(0)), family)
    assert 'var(' not in family and not any(f in family for f in faces), (css, family)


def test_explores_market_chip_wraps_inside_a_phone_row():
    # Tau's Explore chip says the market and its close in one bordered tag ("BTC above $X at midnight ET · closes
    # Oct 28, 04:00 UTC"). Kept on one line (.mk is nowrap) it ran past a 390px screen; in Explore's rows it wraps.
    import re
    from pathlib import Path
    css = (Path(__file__).resolve().parents[1] / 'app' / 'static' / 'app.css').read_text()
    rule = re.search(r'(?m)^#xbody td\.name > \.mk \{([^}]*)\}', css)
    assert rule and 'white-space: normal' in rule.group(1) and 'max-width: 100%' in rule.group(1)
