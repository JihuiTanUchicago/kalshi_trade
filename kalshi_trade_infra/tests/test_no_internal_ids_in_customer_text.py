"""No customer export or customer text shows a strategy's (or a run's) internal id.

The trades CSV wrote "No. 00042" in its strategy column, the strategy page led with it, the credits receipt
named each research debit by its global run id, and chat lines said "[live-ready #12]", "(run #41)" and
"Deployment #12 no longer exists". A customer reads a strategy by its title and a session by its own count
("Session 3"). The grep below holds every module that writes customer text (the server's routes but the
admin page, the services, the emails, the Dev Logs, both bundles and their page files) to that; the
behaviour tests beside each fix (test_trades_csv, test_spend_visibility, test_live_ready_notice,
test_app_agent, test_copilot_context) hold what each surface says instead.

Left as they are, and listed as follow-ups: the engine's own chat lines (app/trading/engine.py, the money
path, "Deployment #12 sold ..."), and the review's context, which the agent reasons over by id.
"""
import pathlib
import re

import pytest

from app.services import customer_text

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "app"

# Modules whose strings a customer reads: every web route but the admin page, the services, the emails,
# the Dev Logs and the shell, and both bundles with their page files (the admin views draw only for staff).
CUSTOMER_PY = sorted(
    [p for p in (APP / "web" / "routes").glob("*.py") if p.name != "admin.py"]
    + list((APP / "services").glob("*.py"))
    + [APP / "adapters" / "ses" / "notify.py", APP / "web" / "devlog.py", APP / "web" / "views.py",
       APP / "web" / "shell_reads.py"])
CUSTOMER_JS = sorted(p for p in (APP / "static").glob("*.js"))

# A zero-padded id ("No. 00042", "%05d", f"{sid:05d}", padStart(5, '0')), in either language.
PADDED = re.compile(r"%0[5-9]d|:0[5-9]d\}|No\.\s*(?:%|\{|\$\{)|padStart\(\s*[5-9]\s*,")
# An id put in a customer's words ("#%d", "run #%s", "Strategy %d", "Deployment #{id}"). "Session %d" is the
# user's own count of their sessions (research_session_numbers), not an id.
NUMBERED = re.compile(r"#%[ds]|#\{|(?:Strategy|Run|Deployment|Experiment) #?%[ds]|\(run #")


def _hits(paths, rx):
    out = []
    for p in paths:
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith(("#", "//", "*", "/*")):
                continue  # a comment may quote what the page once said
            if rx.search(line):
                out.append("%s:%d: %s" % (p.relative_to(ROOT), n, line.strip()[:160]))
    return out


def test_the_customer_modules_are_found():
    names = {p.name for p in CUSTOMER_PY}
    assert {"billing.py", "chat.py", "strategies.py", "customer_text.py", "notify.py", "devlog.py"} <= names
    assert "admin.py" not in names
    assert {"app.js", "app.meridian.js", "app-strategies.js", "app-autopilot.js"} <= {p.name for p in CUSTOMER_JS}


def test_no_customer_module_formats_a_zero_padded_id():
    assert _hits(CUSTOMER_PY + CUSTOMER_JS, PADDED) == []


def test_no_customer_module_numbers_a_strategy_run_or_deployment_by_its_id():
    assert _hits(CUSTOMER_PY, NUMBERED) == []
    # The agent's customer lines (the live-ready notice, a refused research, a missing deployment, the
    # correction) carry no zero-padded id either; its "#%d" lines are the review's context or a once-only
    # marker the chat feed drops (customer_text.unmarked).
    assert _hits([APP / "research" / "agent.py"], PADDED) == []


@pytest.mark.parametrize("stored,shown", [
    ("[live-ready #12] “Fade” cleared every paper-to-live check: 31 trades.", "“Fade” cleared every paper-to-live check: 31 trades."),
    ("[paper-standout #7] “Fade” cleared every paper-to-live check on forward paper.", "“Fade” cleared every paper-to-live check on forward paper."),
    ("[probation #3] Put “Fade” on paper as a forward test.", "Put “Fade” on paper as a forward test."),
    ("[tournament] Retired paper entrant “Fade”.", "[tournament] Retired paper entrant “Fade”."),  # no id in it
])
def test_the_chat_feed_drops_a_once_only_marker_that_names_a_row_number(stored, shown):
    rows = customer_text.chat_rows([{"role": "system", "content": stored}, {"role": "agent", "content": stored}])
    assert rows[0]["content"] == shown
    assert rows[1]["content"] == stored  # the agent's own reply is as it was said


def test_the_last_move_drops_the_marker_too():
    from app.web.routes import chat as chat_routes
    out = chat_routes._last_move({"text": "[live-ready #12] “Fade” cleared every check. Turn on live autopilot.",
                                  "at": "2026-10-27T10:00:00"}, [])
    assert out["text"].startswith("“Fade” cleared") and "#12" not in out["text"]
