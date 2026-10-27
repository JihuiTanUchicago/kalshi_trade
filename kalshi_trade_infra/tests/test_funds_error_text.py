"""Funds' errors are customer text: curly apostrophes, as the page around them has. A key pasted wrong or a
demo exchange that refused read "That isn't a private key" and "Kalshi's demo exchange didn't accept this key"
with straight ones (walked 2026-10-27). Every message the Funds route and the key adapter raise is checked,
from the source, so a new one can't bring a straight apostrophe back."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAISED = {"ApiError", "KalshiKeyError"}


def _messages(rel):
    """Every string constant inside a call to ApiError or KalshiKeyError, and every module-level string the
    module raises by name (PRIVATE_KEY_FORMAT), in the file at `rel`."""
    tree = ast.parse((ROOT / rel).read_text())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) in RAISED:
            out += [c.value for a in node.args for c in ast.walk(a) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "PRIVATE_KEY_FORMAT" for t in node.targets):
            out += [c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    return out


@pytest.mark.parametrize("rel", ["app/web/routes/funds.py", "app/adapters/kalshi/kalshi_account.py"])
def test_funds_errors_use_curly_apostrophes(rel):
    said = _messages(rel)
    assert said, rel
    straight = [m for m in said if "'" in m]
    assert not straight, straight


def test_a_key_that_isnt_one_says_so_with_a_curly_apostrophe():
    from app.adapters.kalshi import kalshi_account

    with pytest.raises(kalshi_account.KalshiKeyError) as e:
        kalshi_account.parse_private_key("not a key")
    assert str(e.value).startswith("That isn’t a private key Kalshi can use.")
