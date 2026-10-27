"""The page files: code only some pages use, split out of each theme's bundle and fetched on first use.

A cold load downloaded and compiled all of app.js (or app.meridian.js) before the first figure showed,
though Dashboard draws from about half of it: on a phone's slow network the bundle's bytes were the
largest part of the cold first-figure time. Each page file holds one area's views (app-<name>.js for
Tau, app.meridian-<name>.js for Meridian); the bundle's router stands in for them (pageView) and runs
the file once it has arrived (pageLoad).

The page shell carries each file's ?v= version for the bundle to fetch it by (#tau-boot data-tau-pages,
data-mer-pages), and a signed-in shell preloads the file its page needs, so that file arrives beside the
bundle instead of a round trip after it (signed out, the page goes to sign-in). Every path a file's
views answer is listed here; tests/test_page_modules.py checks both routers against this table.

A panel file holds what opens over any page rather than a page of its own (the autopilot panel, open):
no path preloads it, and the bundle fetches it the first time it opens.
"""
from __future__ import annotations

import hashlib
import re
from typing import Dict, Optional

# Page file -> the app paths whose view is in it (both themes split the same views out).
PAGES: Dict[str, str] = {
    "research": r"research(?:/\d+)?|example",  # /example goes on to its session's page
    "strategies": r"strategies(?:/\d+)?",
    "funds": r"funds|settings/account",
    "community": r"community",
    "billing": r"billing|settings/billing",
    "admin": r"admin|system|settings/system",
}
# Panel files: opened over any page, so no path's view is in them.
PANELS = ("autopilot",)
NAMES = tuple(PAGES) + PANELS
PREFIX = {"tau": "app-", "meridian": "app.meridian-"}
BUNDLE = {"tau": "app.js", "meridian": "app.meridian.js"}
FILES = tuple(PREFIX[theme] + name + ".js" for theme in PREFIX for name in NAMES)
_PATHS = {name: re.compile(r"^/(?:%s)$" % rx) for name, rx in PAGES.items()}


def file_name(theme: str, name: str) -> str:
    return PREFIX[theme] + name + ".js"


def page_for(path: str) -> Optional[str]:
    """The page file the view at this path is in, or None for a view in the bundle itself."""
    return next((name for name, rx in _PATHS.items() if rx.match(path)), None)


def versions_attr(theme: str, versions: Dict[str, str]) -> str:
    """#tau-boot's data-tau-pages / data-mer-pages: "research:<v>,strategies:<v>,..." (names and hex only)."""
    return ",".join("%s:%s" % (name, versions[file_name(theme, name)]) for name in NAMES)


def build_version(theme: str, versions: Dict[str, str]) -> str:
    """The theme's build as the page knows it (window.__BUILD__, /api/version): its bundle's version and
    its page files' in one hash, so a deploy that changes only a page file still offers a reload."""
    parts = [versions[BUNDLE[theme]]] + [versions[file_name(theme, name)] for name in NAMES]
    return hashlib.sha256(",".join(parts).encode()).hexdigest()[:10]


def preload(theme: Optional[str], path: str, versions: Dict[str, str]) -> str:
    """The <link rel="preload"> for the page file this path's view needs in this theme, else ''.
    An unknown theme (boot.js picks it) preloads nothing: the bundle fetches the file when it runs."""
    name = page_for(path)
    if theme not in PREFIX or name is None:
        return ""
    f = file_name(theme, name)
    return '\n<link rel="preload" href="/static/%s?v=%s" as="script">' % (f, versions[f])
