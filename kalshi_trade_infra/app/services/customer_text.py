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
from typing import Dict, List, Optional

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
NOTICE_FALLBACK = "There's an update on your account."
CHAT_FALLBACK = "The agent hit an internal error here."


def run_rows(runs: List[Dict]) -> List[Dict]:
    """A research session's stored error (an older failed run kept the provider's raw text)."""
    for r in runs:
        if r.get("error"):
            r["error"] = clean(r["error"], RUN_ERROR_FALLBACK)
    return runs


def named(text: Optional[str]) -> Optional[str]:
    """Only an email address or an internal model id replaced where it stands; nothing dropped. For
    text that is the agent's own words or a strategy's code, where a pattern above can be legitimate
    (a thought naming a KeyError, code that raises ValueError, a file called strategy.py)."""
    if not text:
        return text
    return MODEL_ID.sub(A_MODEL, EMAIL.sub(SOMEONE, str(text)))


def event_rows(events: List[Dict]) -> List[Dict]:
    """A run's log lines, and the text values of their data. An error line (the provider's or the
    app's own failure text) goes through ``clean``; every other line is the agent's thinking, steps,
    verdicts and code, which keep their words and only lose an email or a model id (``named``), so a
    thought that mentions an exception never reads as an error."""
    for ev in events:
        if ev.get("kind") == "error":
            ev["message"] = clean(ev.get("message"), EVENT_FALLBACK)
        else:
            ev["message"] = named(ev.get("message"))
        data = ev.get("data")
        if isinstance(data, dict):
            for k, v in list(data.items()):
                if isinstance(v, str):
                    data[k] = named(v)
    return events


def notification_rows(items: List[Dict]) -> List[Dict]:
    """The bell's lines: a name in one is another person's, a reason the engine's or the agent's."""
    for n in items:
        n["body"] = clean(n.get("body"), NOTICE_FALLBACK)
    return items


def chat_rows(messages: List[Dict]) -> List[Dict]:
    """The autopilot panel's lines Tau wrote (role system). The user's own lines and the agent's
    replies are as they were said."""
    for m in messages:
        if m.get("role") == "system":
            m["content"] = clean(m.get("content"), CHAT_FALLBACK)
    return messages
