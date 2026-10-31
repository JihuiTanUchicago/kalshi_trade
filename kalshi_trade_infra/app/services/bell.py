"""The bell's list, shaped for reading: notices about the same thing in a row become one line.

Five comments on one post, or a strategy paused three times while the user was away, used to fill
the list with near-identical lines and push everything else out of its 20 slots. Adjacent notices
of one kind about one page (same `kind` and `link`) collapse into the newest, which carries how
many more it stands for. Grouping is display-only: every row stays stored, read and counted as it
was, and the words of each notice are not changed (engine-written text included).

A group says whether the notices it stands for all say the same words (`alike`): "Bob replied to your post."
over three replies from Carol, Dana and Bob read "and 3 more like this", as if Bob had written all four, and a
live pause over an earlier paper pause of one strategy (another reason, another book) read as one more of the
same. Replies and mentions name who the rest are from (`from`, `from_more`), from their own words.

A notice opens its page at what it is about (`link`, as shown; the stored link is unchanged and is what groups):
a pause at the strategy's Since deploying, where each book's pause and its reason are listed, and a failed
auto-reload at Billing's notice of it. Either page falls back to its heading when that part isn't there."""
import re
from typing import Dict, List, Optional

SHOWN = 20      # lines the bell lists
READ_ROWS = 100  # newest rows read to fill them; a fixed bound however many notices a user has

# Who a reply or a mention is from, as community.py words them ("Bob replied to your post.", "Bob mentioned you
# in a reply."). The name is whatever comes first, so one with odd words in it still reads whole.
_FROM = {"comment": re.compile(r"^(.+) replied to your post\.$", re.S),
         "mention": re.compile(r"^(.+) mentioned you in a (?:post|reply)\.$", re.S)}
FROM_NAMED = 3  # names a group lists before "and N others"

# Where a notice opens, by kind: an element id on its page that pageArrived (both bundles) gives focus to.
_ARRIVE = {"paused": (re.compile(r"^/strategies/\d+$"), "#since-deploying"),
           "reload_failed": (re.compile(r"^/billing$"), "#autorel-fail")}


def _who(kind: str, body: Optional[str]) -> Optional[str]:
    rule = _FROM.get(kind)
    m = rule.match(body or "") if rule else None
    return m.group(1).strip() if m else None


def shown_link(kind: str, link: Optional[str]) -> Optional[str]:
    """The link as the bell opens it: the stored one, with the part of its page the notice is about."""
    rule = _ARRIVE.get(kind)
    return link + rule[1] if rule and link and rule[0].match(link) else link


def grouped(rows: List[Dict], shown: int = SHOWN) -> List[Dict]:
    """`rows` newest first, as list_notifications returns them. Returns at most `shown` items
    ({id, kind, body, link, created_at, read, more, alike, from, from_more, gone}); `read` is False when
    any row it stands for is unread, `alike` False when one of the `more` says other words than `body`,
    `from` the names of the people the `more` are from (a reply's or a mention's: distinct, newest first,
    at most FROM_NAMED, and `from_more` counts the rest), and `gone` True when the strategy it links to is
    no longer the user's. `link` is as the bell opens it (shown_link)."""
    out: List[Dict] = []
    keys: List[Optional[str]] = []  # each line's stored link, which is what groups
    for r in rows:
        last = out[-1] if out else None
        if last is not None and r.get("link") and r.get("kind") == last["kind"] and r.get("link") == keys[-1]:
            last["more"] += 1
            last["read"] = last["read"] and r.get("read_at") is not None
            last["alike"] = last["alike"] and r.get("body") == last["body"]
            who = _who(r["kind"], r.get("body"))
            if who and who not in last["from"] and who not in last["_others"]:
                (last["from"] if len(last["from"]) < FROM_NAMED else last["_others"]).append(who)
            continue
        if len(out) == shown:
            break
        keys.append(r.get("link"))
        out.append({"id": r["id"], "kind": r["kind"], "body": r["body"], "link": shown_link(r["kind"], r.get("link")),
                    "created_at": r["created_at"], "read": r.get("read_at") is not None, "more": 0, "alike": True,
                    "from": [], "_others": [], "gone": bool(r.get("gone"))})
    for n in out:
        n["from_more"] = len(n.pop("_others"))
    return out


def older(rows: List[Dict], items: List[Dict]) -> bool:
    """True when `rows` hold notices past the ones `items` stand for: the bell lists the newest only."""
    return sum(1 + n["more"] for n in items) < len(rows)


def unread_kinds(rows: List[Dict]) -> Dict[str, int]:
    """{kind: unread notices} among `rows`, so a list that filled up while the user was away can open
    with what it holds ("5 put on paper, 1 paused, 1 passed its paper test") before 20 lines of it.
    Counts stored rows, not grouped lines."""
    out: Dict[str, int] = {}
    for r in rows:
        if r.get("read_at") is None:
            out[r["kind"]] = out.get(r["kind"], 0) + 1
    return out
