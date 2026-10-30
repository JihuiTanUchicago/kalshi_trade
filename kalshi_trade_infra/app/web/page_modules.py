"""The page files: code only some pages use, split out of each theme's bundle and fetched on first use.

A cold load downloaded and compiled all of app.js (or app.meridian.js) before the first figure showed,
though Dashboard draws from about half of it: on a phone's slow network the bundle's bytes were the
largest part of the cold first-figure time. Each page file holds one area's views (app-<name>.js for
Tau, app.meridian-<name>.js for Meridian); the bundle's router stands in for them (pageView) and runs
the file once it has arrived (pageLoad).

The page shell carries each file's ?v= version for the bundle to fetch it by (#tau-boot data-tau-pages,
data-mer-pages), and a signed-in shell preloads the file its page needs, so that file arrives beside the
bundle instead of a round trip after it (signed out, the page goes to sign-in, except a public page's:
Terms and Privacy draw signed out, so their shell preloads their file either way). Every path a file's
views answer is listed here; tests/test_page_modules.py checks both routers against this table.

A panel file holds what opens over any page rather than a page of its own (the autopilot panel, open):
no path preloads it, and the bundle fetches it the first time it opens.
"""
from __future__ import annotations

import hashlib
import re
from typing import Dict, Optional, Tuple

# Page file -> the app paths whose view is in it (both themes split the same views out, apart from TAU_ONLY).
PAGES: Dict[str, str] = {
    "research": r"research(?:/\d+)?|example",  # /example goes on to its session's page
    "strategies": r"strategies(?:/\d+)?",
    "funds": r"funds|settings/account",
    "community": r"community",
    "billing": r"billing|settings/billing",
    "admin": r"admin|system|settings/system",
    "legal": r"terms|privacy",
}
# Panel files: opened over any page, so no path's view is in them.
PANELS = ("autopilot",)
NAMES = tuple(PAGES) + PANELS
# Page files only Tau has: its Terms and Privacy pages, which boot.js serves in Tau for everyone.
TAU_ONLY = ("legal",)
# Page files whose pages draw signed out, so a signed-out shell preloads them too.
PUBLIC = ("legal",)
# A page's own static files beside its page file. No shell links them, not even their page's: the page
# file asks the bundle for them once its first figures have painted (pageAssets, #tau-boot
# data-page-assets), so they never hold its first figure back. The Funds shell linked them, three
# stylesheets render-blocking in <head> and three scripts deferred ahead of the bundle (defer runs in
# order), so a cold Funds waited on them for its first figure. Funds': the native perps account (its box
# mounts once its script is in), and the broker connection and Alpaca paper files kept with it (Funds
# doesn't offer those controls for now).
ASSETS: Dict[str, Tuple[str, ...]] = {
    "funds": ("broker-connections.css", "alpaca-paper.css", "kalshi-perps-live.css",
              "alpaca-paper.js", "kalshi-perps-live.js", "broker-connections.js"),
}
PREFIX = {"tau": "app-", "meridian": "app.meridian-"}
BUNDLE = {"tau": "app.js", "meridian": "app.meridian.js"}


def names(theme: str) -> Tuple[str, ...]:
    """The page and panel files this theme has."""
    return tuple(name for name in NAMES if theme == "tau" or name not in TAU_ONLY)


FILES = tuple(PREFIX[theme] + name + ".js" for theme in PREFIX for name in names(theme))
_PATHS = {name: re.compile(r"^/(?:%s)$" % rx) for name, rx in PAGES.items()}


def file_name(theme: str, name: str) -> str:
    return PREFIX[theme] + name + ".js"


def page_for(path: str) -> Optional[str]:
    """The page file the view at this path is in, or None for a view in the bundle itself."""
    return next((name for name, rx in _PATHS.items() if rx.match(path)), None)


def versions_attr(theme: str, versions: Dict[str, str]) -> str:
    """#tau-boot's data-tau-pages / data-mer-pages: "research:<v>,strategies:<v>,..." (names and hex only)."""
    return ",".join("%s:%s" % (name, versions[file_name(theme, name)]) for name in names(theme))


def build_version(theme: str, versions: Dict[str, str]) -> str:
    """The theme's build as the page knows it (window.__BUILD__, /api/version): its bundle's version and
    its page files' in one hash, so a deploy that changes only a page file still offers a reload."""
    parts = [versions[BUNDLE[theme]]] + [versions[file_name(theme, name)] for name in names(theme)]
    return hashlib.sha256(",".join(parts).encode()).hexdigest()[:10]


def preload(theme: Optional[str], path: str, versions: Dict[str, str], signed_in: bool = True) -> str:
    """The <link rel="preload"> for the page file this path's view needs in this theme, else ''.
    An unknown theme (boot.js picks it) preloads nothing: the bundle fetches the file when it runs.
    Signed out, only a PUBLIC page's file: any other page goes to sign-in instead."""
    name = page_for(path)
    if theme not in PREFIX or name is None or name not in names(theme) or not (signed_in or name in PUBLIC):
        return ""
    f = file_name(theme, name)
    return '\n<link rel="preload" href="/static/%s?v=%s" as="script">' % (f, versions[f])


# Each theme's text face, as its stylesheet's @font-face names it (self-hashed, so always this URL). Meridian
# draws every page in DM Sans, but the browser asked for the file only once the bundle had drawn text that
# needs it: the page painted in the fallback face, then laid the whole page out again when DM Sans arrived
# (a second full layout, and every line moving). Tau's app pages use the system face (Rubik is its landing's
# only), so its shell preloads none.
FONTS: Dict[str, str] = {"meridian": "dm-sans-latin-9fea608a94.woff2"}


def font_preload(theme: Optional[str], signed_in: bool = True) -> str:
    """The <link rel="preload"> for the theme's text face, so it downloads beside the stylesheet and the bundle
    and is in hand when the first page is laid out; '' for a theme without one, an unknown theme, or signed out
    (the sign-in and landing pages set their own type). Fonts are always fetched in CORS mode, so the preload
    says crossorigin, or the browser would fetch the file twice."""
    f = FONTS.get(theme or "") if signed_in else None
    return '\n<link rel="preload" href="/static/%s" as="font" type="font/woff2" crossorigin>' % f if f else ""


def assets_attr(versions: Dict[str, str]) -> str:
    """#tau-boot's data-page-assets: "funds:/static/alpaca-paper.css?v=<v> funds:..." (names, paths and hex
    only), in ASSETS' order: the URLs the bundle loads them by."""
    return " ".join("%s:/static/%s?v=%s" % (name, f, versions[f]) for name, files in ASSETS.items() for f in files)
