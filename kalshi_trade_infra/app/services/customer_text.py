"""Text a customer reads that was built from stored rows, made safe to show.

Rows are written by many hands: the engine, the research agent, a provider's error, an admin
tool, an exchange's answer. Some of that text was never meant for the customer: an admin grant's
memo named the staff member who made it, and an older failed run kept the provider's raw error. The
rows stay as written (they are the record); what a customer sees goes through ``clean`` on the way
out, and a person's display name through ``display_name``.

What never reaches a customer (``leaks`` names each kind; tests pin it on every render path):
    email      an email address (another user's, or staff's)
    model_id   an internal, invokable model id ("us.anthropic.claude-opus-4-6-v1"); the page names
               the model by its catalog label instead
    secret     an AWS or credential-store name: an ARN, an access key id, a Secrets Manager or
               parameter id, a secret's env var name, a Stripe secret
    host       an internal hostname or private address (*.amazonaws.com, *.internal, ip-10-...)
    path       a server file path or source file name
    raw_error  a raw exception: a traceback, a repr, a library's error text, an HTML error page

Pure: no I/O, no app imports, so every layer can use it.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional

from trading_core.domain.money import cents

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
MODEL_ID = re.compile(
    r"(?:\b(?:us|eu|apac|global)\.)?\b(?:anthropic\.claude|amazon\.(?:nova|titan)|meta\.llama|writer\.palmyra"
    r"|deepseek\.r\d|mistral\.[a-z]|cohere\.command|ai21\.)(?:[\w.:-]*\w)?"
    r"|\bclaude-[a-z0-9](?:[\w.:-]*\w)?", re.I)
SECRET = re.compile(
    r"\barn:aws[\w-]*:|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bsecretsmanager\b|\bSecrets ?Manager\b|\bSecret(?:Id|String)\b"
    r"|\bParameter ?Store\b|\b(?:ssm|kms):|\baws_(?:access_key_id|secret_access_key|session_token)\b"
    r"|\b[A-Z][A-Z0-9]*_(?:API_KEY|SECRET(?:_KEY)?|ACCESS_KEY(?:_ID)?|TOKEN|PASSWORD)\b"
    r"|\b(?:sk|rk)_(?:live|test)_\w+|\bwhsec_\w+|\b[\w-]+/[\w-]*(?:api_key|secret|password)\b", re.I)
HOST = re.compile(
    r"\b[\w-]+(?:\.[\w-]+)*\.(?:amazonaws\.com|compute\.internal|ec2\.internal|internal|localdomain)\b"
    r"|\bip-\d{1,3}(?:-\d{1,3}){3}\b|\blocalhost\b"
    r"|\b(?:10|127)(?:\.\d{1,3}){3}\b|\b192\.168(?:\.\d{1,3}){2}\b|\b172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}\b",
    re.I)
PATH = re.compile(r"(?<![\w.])/(?:home|opt|srv|var|etc|usr|tmp|root|mnt|proc)/\S*"
                  r"|\b[\w-]+\.(?:py|pyc|pem|sql)\b|\bkalshi_trade(?:_infra)?\b|\bsite-packages\b")
RAW_ERROR = re.compile(
    r"Traceback \(most recent call last\)|\bFile \"[^\"]*\", line \d+|\b[A-Z][A-Za-z]*(?:Error|Exception)\s*[:(]"
    r"|\b(?:botocore|boto3|pymysql|urllib3|requests\.exceptions|HTTPSConnectionPool)\b|An error occurred \("
    r"|\[Errno \d+\]|Max retries exceeded|\b(?:ValidationException|ThrottlingException|AccessDenied\w*)\b"
    r"|<\s*(?i:!doctype|html|head|body|title)\b")

KINDS: Dict[str, "re.Pattern[str]"] = {"email": EMAIL, "model_id": MODEL_ID, "secret": SECRET, "host": HOST,
                                       "path": PATH, "raw_error": RAW_ERROR}
# Kinds that mean the text is an internal message, not a sentence for the customer: nothing in it is
# kept. An email or a model id inside an otherwise plain sentence is replaced where it stands.
_INTERNAL = ("secret", "host", "path", "raw_error")

SOMEONE = "someone"
A_MODEL = "the AI model"


def leaks(text: Optional[str]) -> List[str]:
    """The kinds above that ``text`` contains, in KINDS order; [] when it is safe to show."""
    s = str(text or "")
    return [k for k, rx in KINDS.items() if rx.search(s)]


def clean(text: Optional[str], fallback: Optional[str] = "") -> Optional[str]:
    """``text`` as a customer may read it: an email address reads "someone" and an internal model id
    "the AI model"; text that carries anything internal (a raw error, a host, a path, a secret's name)
    is replaced whole by ``fallback``. None and "" come back as given."""
    if not text:
        return text
    s = str(text)
    if any(KINDS[k].search(s) for k in _INTERNAL):
        return fallback
    return MODEL_ID.sub(A_MODEL, EMAIL.sub(SOMEONE, s))


# The pages write an apostrophe curly ("isn’t"), and so do the autopilot panel's own summary lines (its story and
# idle line). Words another module wrote that a line quotes (the engine's entry scan, a stored pause reason) go
# through ``curly`` on the way out, so one line never mixes the two. Only an apostrophe inside a word changes.
_STRAIGHT_APOSTROPHE = re.compile(r"(?<=[A-Za-z])'(?=[A-Za-z])")


def curly(text: Optional[str]) -> Optional[str]:
    """``text`` with each in-word straight apostrophe ("isn't") curly ("isn’t"); None and "" as given."""
    return _STRAIGHT_APOSTROPHE.sub("’", text) if text else text


# The autopilot panel's line when a chat turn failed: the research agent writes it, and the chat read knows a turn
# ended by it (chat._answer_line). One wording for both. A row stored before 2026-10-27 says "didn't" straight: it
# reads curly (chat_rows) and still ends its turn.
NO_ANSWER = "The agent hit an error and didn’t answer."
NO_ANSWER_LINE = NO_ANSWER + " Send your message again, or try in a minute."

# The autopilot's line for an action it has no handler for (the research agent's act() fall-through). Until
# 2026-10-28 it named the action's raw kind in brackets ("I tried an action I’m not allowed to take (research)."),
# a word from the model's action format; the journal keeps the kind. An older stored line reads as the new one
# (chat_rows).
UNKNOWN_ACTION_LINE = "I tried an action I’m not allowed to take, so nothing changed."
_UNKNOWN_ACTION = re.compile(r"^I tried an action I[’']m not allowed to take \([^)]*\)\.$")


def unknown_action_line(text: Optional[str]) -> Optional[str]:
    """An older "I tried an action I’m not allowed to take (<kind>)." line as it reads now, else ``text``."""
    return UNKNOWN_ACTION_LINE if text and _UNKNOWN_ACTION.match(str(text).strip()) else text


def display_name(name: Optional[str], fallback: str) -> str:
    """A person's name as other people see it: their name, or ``fallback`` when there is none or it
    carries an email address (a Google profile with no name set can use the address as its name)."""
    s = (name or "").strip()
    return s if s and not leaks(s) else fallback


# -- stored rows, as the pages send them ---------------------------------------------------------
# Each cleans, in place, the text a customer reads in the rows a read returned, and returns them so
# a handler can wrap its read in one call.

RUN_ERROR_FALLBACK = None  # the page says "This session stopped on an error." on its own
EVENT_FALLBACK = "The agent hit an internal error on this step."
NOTICE_FALLBACK = "There’s an update on your account."
CHAT_FALLBACK = "The agent hit an internal error here."


def run_rows(runs: List[Dict]) -> List[Dict]:
    """A research session's stored error (an older failed run kept the provider's raw text)."""
    for r in runs:
        if r.get("error"):
            r["error"] = ladder_words(clean(r["error"], RUN_ERROR_FALLBACK))
    return runs


def named(text: Optional[str]) -> Optional[str]:
    """Only an email address or an internal model id replaced where it stands; nothing dropped. For
    text that is the agent's own words or a strategy's code, where a pattern above can be legitimate
    (a thought naming a KeyError, code that raises ValueError, a file called strategy.py)."""
    if not text:
        return text
    return MODEL_ID.sub(A_MODEL, EMAIL.sub(SOMEONE, str(text)))


# A research log line written before 2026-10-30 named a strike-ladder market by its family label's placeholder
# ("Chose to research Bitcoin above $X at 5pm ET"); it reads in words, as new lines are written (the market's
# customer_label, app.trading.markets). The stored line is unchanged.
_LADDER_PLACEHOLDER = re.compile(r"\babove \$X\b")
LADDER_WORDS = "a set price"


def ladder_words(text: Optional[str]) -> Optional[str]:
    """``text`` with an older family label's "above $X" in words ("above a set price"); None and "" as given."""
    return _LADDER_PLACEHOLDER.sub("above " + LADDER_WORDS, text) if text else text


def event_rows(events: List[Dict]) -> List[Dict]:
    """A run's log lines, and the text values of their data. An error line (the provider's or the
    app's own failure text) goes through ``clean``; every other line is the agent's thinking, steps,
    verdicts and code, which keep their words and only lose an email or a model id (``named``), so a
    thought that mentions an exception never reads as an error."""
    for ev in events:
        if ev.get("kind") == "error":
            ev["message"] = ladder_words(clean(ev.get("message"), EVENT_FALLBACK))
        else:
            ev["message"] = ladder_words(named(ev.get("message")))
        data = ev.get("data")
        if isinstance(data, dict):
            for k, v in list(data.items()):
                if isinstance(v, str):
                    data[k] = ladder_words(named(v))
    return events


# The bell lines whose words are billing's own and say an apostrophe straight as stored ("Auto-reload couldn't
# add ... in credits."; billing.RELOAD_FAILED_KIND): the bell reads them curly, as Billing's banner does, and
# their dollar figure grouped (grouped_dollars). Every
# other kind keeps its stored words (the engine's kill switch, pause and fill lines are said as written).
CURLY_KINDS = frozenset({"reload_failed"})


# A dollar figure billing wrote with no thousands separator ("$1000.00", reload_failed_body's "%s" of a Decimal):
# the bell and Billing's banner read it grouped ("$1,000.00"), as every other figure on the page is.
_UNGROUPED_DOLLARS = re.compile(r"\$(\d{4,})(?=\.\d{2}(?!\d))")


def grouped_dollars(text: Optional[str]) -> Optional[str]:
    """``text`` with each "$1000.00" as "$1,000.00"; None and "" as given."""
    return _UNGROUPED_DOLLARS.sub(lambda m: "$" + "{:,}".format(int(m.group(1))), text) if text else text


def notification_rows(items: List[Dict]) -> List[Dict]:
    """The bell's lines: a name in one is another person's, a reason the engine's or the agent's."""
    for n in items:
        n["body"] = clean(n.get("body"), NOTICE_FALLBACK)
        if n.get("kind") in CURLY_KINDS:
            n["body"] = grouped_dollars(curly(n["body"]))
    return items


def chat_rows(messages: List[Dict], paused: Optional[Dict[int, Dict]] = None,
              focus_words: Optional[Callable[[List[str]], str]] = None) -> List[Dict]:
    """The autopilot panel's lines Tau wrote (role system). The user's own lines and the agent's
    replies are as they were said. A once-only line's marker ("[live-ready #12]") is dropped (unmarked).
    A risk or execution change an older line wrote as the setting's
    key ("max_open_notional=200.0") reads in words, as new lines are written (control_changes).
    The engine's "Paused deployment #N automatically. <why>" reads as the "Last move" line does
    (auto_pause_line), and its "Deployment #N sold ..." stop-loss line in words (stop_sold_line), each by
    the strategy's name from ``paused`` ({deployment id: {"title", "mode"}} for the ids auto_paused_ids
    lists); the row number and the ticker never reach the page, and the stored line is unchanged. An
    older "Market focus set to btc." names the focus in words through ``focus_words`` (the research
    agent's, which this module can't import), as new lines are written (focus_set_line)."""
    for m in messages:
        if m.get("role") == "system":
            text = m.get("content")
            if text and curly(str(text)).startswith(NO_ANSWER):
                text = curly(str(text))
            dep = auto_paused_id(text)
            if dep is not None:
                text = auto_pause_line(text, (paused or {}).get(dep))
            dep = stop_sold_id(text)
            if dep is not None:
                text = stop_sold_line(text, (paused or {}).get(dep))
            m["content"] = plain_controls(clean(unknown_action_line(focus_set_line(unmarked(text), focus_words)), CHAT_FALLBACK))
    return messages


# "Market focus set to btc." (the focus route) and "Market focus set to btc, eth. Autopilot will research, ..."
# (the autopilot's set_focus) named the focus by its stored tokens until 2026-10-27, right under the panel's
# own "Focus: Bitcoin". A token is lowercase with no space, so a line already in words ("Bitcoin", "daily high
# temperatures") is left as it is.
_FOCUS_SET = re.compile(r"^(Market focus set to )([a-z0-9_-]+(?:, [a-z0-9_-]+)*)(?=\.(?:\s|$))")


def focus_set_line(text: Optional[str], focus_words: Optional[Callable[[List[str]], str]]) -> Optional[str]:
    """A "Market focus set to <tokens>." line with the tokens in words (``focus_words``), else as given."""
    if not text or focus_words is None:
        return text
    m = _FOCUS_SET.match(str(text))
    if not m:
        return text
    return m.group(1) + focus_words(m.group(2).split(", ")) + str(text)[m.end():]


# A once-only line (agent.live_ready_notices, auto_paper_probation) leads with a marker that names the
# strategy's row number, "[live-ready #12]", which repo.chat_contains finds so the line is said once. The
# stored line keeps it; what a customer reads never does.
_ONCE_MARKER = re.compile(r"^\[[a-z-]+ #\d+\]\s*")


def unmarked(text: Optional[str]) -> Optional[str]:
    """``text`` without its leading once-only marker ("[live-ready #12] "), and a paper tournament line
    (tournament_line) in the app's words, else as given."""
    if not text:
        return text
    return tournament_line(_ONCE_MARKER.sub("", str(text), count=1))


# The hourly paper tournament (research/tournament.rebalance) leads its chat lines with "[tournament]" and says
# them in its own terms: a "paper entrant", "Retired", a "posterior mean", "the live book", the "next near miss",
# the "forward sample". The panel showed them so. The stored line keeps them (it is the record); a customer
# reads what happened in the words the app uses elsewhere: a deployment taken off paper is "removed" (Deploy's
# Remove button), and a strategy that came close to passing research takes its place.
_TOURNAMENT = re.compile(r"^\[tournament\]\s*")
_TOURNAMENT_WORDS = (
    (re.compile(r"^Retired paper entrant (“.+?”): "), r"Removed \1 from paper: "),
    (re.compile(r"^Resumed paper entrant (“.+?”) "), r"Resumed \1 on paper "),
    (re.compile(r" \(posterior mean [+-]?\d+(?:\.\d+)?% of stake\)"), ""),
    (re.compile(r"\bno trade in (\d+) days on paper: its entry rule never fires on the live book\b"),
     r"no trade in \1 days, as its entry rule never fired on the market’s real prices"),
    (re.compile(r"\bIts slot goes to the next near miss\."), "Its place goes to the next strategy that came close to passing research."),
    (re.compile(r"\bpausing would cut the forward sample short\."), "pausing would cut its paper test short."),
)


# The autopilot's refusal to pause a tournament entrant (agent._tournament_hold) says it in the same terms, and
# its net as "$%.2f" ("$-1.20"). The panel heads it "Autopilot's rule: kept running" by its opening words, which
# the plain line keeps ("I left <title> running: it ").
_HOLD = re.compile(r"^(I left .+? running: it )is a paper tournament entrant with (\d+) of (\d+) independent events "
                   r"\(\$(-?\d+(?:\.\d+)?) (net of fees and spread)\), and the tournament retires it on its own once the "
                   r"data can judge it\. Paper costs nothing; a pause now only shrinks the forward sample\.$")


def _signed_usd(v: str) -> str:
    c = cents(v)
    return ("−" if c < 0 else "+") + _usd(abs(c))


def tournament_line(text: Optional[str]) -> Optional[str]:
    """A "[tournament] ..." chat line without its marker and in plain words, and the autopilot's "I left it
    running" for a tournament entrant the same way; any other text as given."""
    if text and _HOLD.match(str(text)):
        m = _HOLD.match(str(text))
        return ("%sis in its paper test, with %s of the %s separate events it needs (%s %s), and it is removed on "
                "its own once there are enough to judge it. Paper costs nothing; a pause now only cuts its paper test "
                "short." % (m.group(1), m.group(2), m.group(3), _signed_usd(m.group(4)), m.group(5)))
    if not text or not _TOURNAMENT.match(str(text)):
        return text
    return tournament_reason(_TOURNAMENT.sub("", str(text), count=1))


def tournament_reason(text: Optional[str]) -> Optional[str]:
    """The tournament's own terms in ``text`` (_TOURNAMENT_WORDS) in plain words: a chat line without its marker,
    or a reason on its own, tournament.verdict's ("after 31 paper events it is 93% likely to be losing money per
    event (posterior mean -4.2% of stake)") as the Research page's Paper tournament shows it, the same words its
    removal line says in the autopilot feed. Text with none of them is as given."""
    if not text:
        return text
    s = str(text)
    for rx, words in _TOURNAMENT_WORDS:
        s = rx.sub(words, s)
    return s


# What rebalance stores as the reason on a deployment it stops ("Tournament: retired, <verdict>"), which a removed
# deployment's row and its strategy page show as its status reason.
_RETIRED_REASON = re.compile(r"^Tournament: retired, (.+)$", re.S)


def tournament_status(text: Optional[str]) -> Optional[str]:
    """A deployment's stored "Tournament: retired, <reason>" as "The paper tournament removed it: <reason>" in
    plain words (tournament_reason); any other reason as given."""
    m = _RETIRED_REASON.match(str(text or ""))
    return "The paper tournament removed it: " + tournament_reason(m.group(1)) if m else text


def tournament_standings(st: Optional[Dict]) -> Optional[Dict]:
    """tournament.standings as the Research page reads it: each strategy's reason for coming off paper
    (``verdict``) in plain words (tournament_reason). In place; the standings' figures are as computed."""
    for r in (st or {}).get("entrants") or []:
        if r.get("verdict"):
            r["verdict"] = tournament_reason(r["verdict"])
    return st


def auto_paused_ids(messages: List[Dict]) -> List[int]:
    """The deployments the engine's automatic-pause and stop-loss sale lines among ``messages`` name, for one
    read of their names before chat_rows."""
    ids = (auto_paused_id(m.get("content")) or stop_sold_id(m.get("content"))
           for m in messages if m.get("role") == "system")
    return sorted({i for i in ids if i is not None})


# -- risk and execution controls, in words ---------------------------------------------------------
# The autopilot's risk/execution changes name a user setting by its column. A proposal read
# "drawdown_limit_pct=20.0, max_open_notional=200.0" over Approve, so nobody could tell what it changed.

def _usd(v: float) -> str:
    return "${:,.2f}".format(v)


CONTROL_WORDS = {
    "drawdown_limit_pct": lambda v: "a strategy stops once it is down {:g}% of its capital".format(round(v, 2)),
    "max_open_positions": lambda v: "at most {:d} open position{}".format(int(v), "" if int(v) == 1 else "s"),
    "max_open_notional": lambda v: "at most {} in open positions".format(_usd(v)),
    "exec_max_book_fraction": lambda v: "each order takes at most {:g}% of the contracts on offer".format(round(v * 100, 1)),
    "exec_max_entry_spread": lambda v: "no entry when the spread is wider than {:g}¢".format(round(v * 100, 1)),
    "exec_max_order_notional": lambda v: "at most {} per order".format(_usd(v)),
}
_CONTROL_SETTING = re.compile(r"\b(%s)=(-?\d+(?:\.\d+)?)" % "|".join(CONTROL_WORDS))


def control_changes(changes: Dict) -> str:
    """A risk or execution change set ({setting: value}) in words, in the order given; a setting not
    listed above keeps its name."""
    return ", ".join(CONTROL_WORDS[k](float(v)) if k in CONTROL_WORDS else "%s %s" % (k.replace("_", " "), v)
                     for k, v in changes.items())


def plain_controls(text: Optional[str]) -> Optional[str]:
    """``text`` with every "setting=value" of a control above put in words."""
    if not text or "=" not in text:
        return text
    return _CONTROL_SETTING.sub(lambda m: CONTROL_WORDS[m.group(1)](float(m.group(2))), str(text))


# -- the engine's automatic pause, in words ---------------------------------------------------------
# The engine posts "Paused deployment #12 automatically. <why>" when its loss guard or the drawdown
# limit stops a strategy (trading/engine.py; that text stays as written). It names a row number nobody
# sees, so the autopilot card's "Last move" says it by the strategy's name instead.

_AUTO_PAUSE = re.compile(r"^Paused deployment #\d+ automatically\.?\s*(.*)$", re.S)
_AUTO_PAUSE_ID = re.compile(r"^Paused deployment #(\d+) automatically\b")


def auto_paused_id(text: Optional[str]) -> Optional[int]:
    """The deployment the engine's "Paused deployment #N automatically" line names, else None."""
    m = _AUTO_PAUSE_ID.match(str(text or ""))
    return int(m.group(1)) if m else None
_NUM = r"(\d+(?:\.\d+)?)"
_MONEY = r"\$([\d,]+(?:\.\d+)?)"
_PAUSE_WHY = (
    (re.compile(r"^Lost %s, more than the %s guard\b" % (_MONEY, _MONEY)),
     lambda m: "it lost $%s, more than its $%s loss guard" % (m.group(1), m.group(2))),
    (re.compile(r"^Live is down %s over its first (\d+) closed trades\b" % _MONEY),
     lambda m: "it is down $%s over its first %s real-money trades" % (m.group(1), m.group(2))),
)
_FORCE_WHY = (
    (re.compile(r"^drawdown %s%% >= limit %s%%$" % (_NUM, _NUM)),
     lambda m: "it was down %s%% of its capital, past your %s%% limit" % (m.group(1), m.group(2))),
    (re.compile(r"^position down %s%% >= stop %s%% of cost$" % (_NUM, _NUM)),
     lambda m: "a position fell %s%% below its cost, past your %s%% stop" % (m.group(1), m.group(2))),
)
_PAUSE_BOOK = {"paper": "paper", "demo": "demo", "live": "live"}


def _pause_reason(why: str) -> str:
    why = why.strip()
    for rx, say in _PAUSE_WHY:
        m = rx.match(why)
        if m:
            return say(m)
    if why.startswith("force-closed:"):
        parts = []
        for part in why[len("force-closed:"):].split(";"):
            for rx, say in _FORCE_WHY:
                m = rx.match(part.strip())
                if m:
                    parts.append(say(m))
        return " and ".join(parts)
    return ""  # a reason not listed above: the name and the book alone, never the engine's raw words


def auto_pause_line(text: Optional[str], deployment: Optional[Dict]) -> Optional[str]:
    """The engine's "Paused deployment #N automatically. <why>" as a customer reads it: the strategy by
    its name (``deployment``'s title, "one of your strategies" once it is gone), its book, and the guard
    that fired in words. Any other line comes back as given."""
    m = _AUTO_PAUSE.match(str(text or ""))
    if not m:
        return text
    d = deployment or {}
    title, book = (d.get("title") or "").strip(), _PAUSE_BOOK.get(d.get("mode") or "")
    name = ("your %s strategy %s" % (book, title) if book else title) if title else "one of your strategies"
    why = _pause_reason(m.group(1))
    return "Paused %s automatically%s." % (name, (": " + why) if why else "")


# -- the engine's stop-loss sale, in words ------------------------------------------------------------
# The engine posts "Deployment #12 sold NO KXBTC15M-26OCT271415-15: down 42.0% >= stop 40.0% of cost. The rest
# of the deployment keeps trading." when one position falls past the user's stop (trading/engine.py; that text
# stays as written). In the panel's feed it named a row number, the contract's raw ticker and a ">=", under
# "Reviewed". The feed says it by the strategy's name, as the automatic pause is said.

_STOP_SOLD = re.compile(r"^Deployment #(\d+) sold (YES|NO) \S+: down (\d+(?:\.\d+)?)% >= stop (\d+(?:\.\d+)?)% of cost\.")


def stop_sold_id(text: Optional[str]) -> Optional[int]:
    """The deployment the engine's "Deployment #N sold ..." stop-loss line names, else None."""
    m = _STOP_SOLD.match(str(text or ""))
    return int(m.group(1)) if m else None


def stop_sold_line(text: Optional[str], deployment: Optional[Dict]) -> Optional[str]:
    """The engine's stop-loss sale as a customer reads it: which side was sold, the strategy by its name and book
    (``deployment``, "one of your strategies" once it is gone), and the stop in words. Any other line comes back
    as given."""
    m = _STOP_SOLD.match(str(text or ""))
    if not m:
        return text
    d = deployment or {}
    title, book = (d.get("title") or "").strip(), _PAUSE_BOOK.get(d.get("mode") or "")
    name = ("your %s strategy %s" % (book, title) if book else title) if title else "one of your strategies"
    return ("Sold a %s position of %s automatically: it fell %s%% below its cost, past your %s%% stop. "
            "The rest of the strategy keeps trading." % (m.group(2), name, m.group(3), m.group(4)))


# -- what a paper P&L includes ----------------------------------------------------------------------
# Every page that shows a paper P&L says what a paper fill assumes: PAPER_NET beside the figure, and
# PAPER_FILLS where there is room (the track record's method, the pages' info bubble). Both bundles and
# track_record.METHOD carry the same words, and tests/test_paper_fill_copy.py pins them to these and to
# the fill model. They say what the fill model does today:
#   price   a buy fills at the ask and a sell at the bid of a quote at most 2s old (SimulatedVenue,
#           data_pipeline/architecture/simulated_venue.py; the legacy instant fill buys at the ask too)
#   fee     Kalshi's taker fee on every fill (kalshi_fees.taker_fee_dollars), none at settlement
#   size    only the contracts resting at that price; the rest of the order doesn't fill
#   settle  $1 or $0 on Kalshi's result (engine.settle_due)
# That already pays the taker cost measured on Kalshi's books (app/trading/exec_cost_model.py: about
# 0.45c of half-spread plus 1.75c of fee a contract at the median book). What it leaves out is the ask
# moving in the second or two before a real order lands (0.2c at 1s, 0.55c at 2s on average): the
# dashboard, the strategy page and the track record show paper P&L after it beside the figure, as an
# estimate (trading_core.domain.slippage, 0.5c a contract each time an order fills; owner, 2026-10-27).
# A change to the fill model changes these words with it.
PAPER_NET = "after Kalshi fees and the spread"
# The same, where a sentence already runs long (the backtest comparison, the autopilot's chat lines).
PAPER_NET_SHORT = "net of fees and spread"
PAPER_FILLS = ("Paper trades against Kalshi’s live order book: it buys at the ask and sells at the bid, pays "
               "Kalshi’s trading fee on every fill, and fills only the contracts offered at that price. A "
               "contract held to the end settles at $1 or $0. It doesn’t model the price moving in the second or "
               "two before a real order lands. Where a page shows an estimate after typical live slippage, it takes "
               "0.5¢ a contract off each time an order fills to allow for that.")
