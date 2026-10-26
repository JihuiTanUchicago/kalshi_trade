"""Every unit deploy_web.sh installs runs on the box's Python 3.13 venv.

/opt/kalshi/.venv is Python 3.9: app code (dataclass slots=True) doesn't import there. On 2026-10-26
tau-code-paper ran on it and every hourly replay died at import, so no code strategy reached paper.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_units_deploy_web_installs_use_the_313_venv():
    script = (ROOT / "scripts" / "deploy_web.sh").read_text()
    units = re.search(r'^UNITS=\$\{UNITS:-"([^"]*)"\}', script, re.M).group(1).split()
    services = [u for u in units if u.endswith(".service")]
    assert services
    for u in services:
        text = (ROOT / "scripts" / "systemd" / u).read_text()
        pythons = re.findall(r"/opt/kalshi/\.venv\w*/bin/python", text)
        assert pythons and all(p == "/opt/kalshi/.venv313/bin/python" for p in pythons), u
