"""The theme bundles, their page files and stylesheets, served without their comments.

The source is written for people: about a quarter of app.js's compressed bytes are comments, and on a
phone's slow network every byte of the bundle and the render-blocking stylesheet is time before the
first figure. There is no build step, so the server leaves them out as it serves each file: in JS each
line that is a // comment and nothing else, in CSS each /* comment */. Every line stays where it was
(a JS line goes blank, a CSS comment keeps its newlines), so a page error report's line:col (boot.js,
client_errors) and the browser's own error lines still point at the line in the source file.

A comment is left out only where the scanner is sure it is one: never inside a string, a template
literal or a regex. A file it can't read to the end in that way (a quote or a template it never sees
closed) goes out as it is. The ?v= version, the ETag and CloudFront's key stay the source file's hash:
what goes out is worked out from those bytes alone, once per version.
"""
from __future__ import annotations

import re
import threading
from typing import Dict, List, Tuple

from app.web import page_modules

# Only the files that are most of a cold load's bytes. The others are small and go out as they are.
NAMES = frozenset(("app.css", "app.meridian.css") + tuple(page_modules.BUNDLE.values()) + page_modules.FILES)

# A / after one of these is division; after anything else (an operator, a keyword such as return, an
# opening brace) it starts a regex. The tokens kept: "id" (a name, a number, a string), ")", "]", "}".
_DIVIDES_AFTER = ("id", ")", "]", "}")
_KEYWORDS = frozenset(("return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw",
                       "yield", "await", "instanceof"))
_WORD = re.compile(r"[A-Za-z0-9_$]+")

_CACHE: Dict[Tuple[str, str], bytes] = {}
_LOCK = threading.Lock()


def js_comment_lines(src: str) -> List[int]:
    """The 1-based numbers of the lines that are a // comment and nothing else (leading spaces aside).
    Raises ValueError on anything it can't follow: a string or regex running into a newline, a block
    comment or template literal never closed."""
    out: List[int] = []
    i, n, line = 0, len(src), 1
    # One entry per nesting: ["code", open braces] or ["tpl", 0]. A template's ${ opens code inside it,
    # and the } that matches it (no braces open in that code) goes back to the template.
    stack: List[list] = [["code", 0]]
    last = ""
    line_start = True
    while i < n:
        c = src[i]
        if stack[-1][0] == "tpl":
            if c == "\\":
                line += src[i + 1:i + 2] == "\n"
                i += 2
            elif c == "`":
                stack.pop()
                i += 1
                last = "id"
            elif src.startswith("${", i):
                stack.append(["code", 0])
                i += 2
                last = ""
            else:
                line += c == "\n"
                i += 1
            continue
        if line_start:
            j = i
            while j < n and src[j] in " \t":
                j += 1
            if src.startswith("//", j):
                out.append(line)
            line_start = False
        if c == "\n":
            line += 1
            line_start = True
            i += 1
        elif c in " \t\r":
            i += 1
        elif src.startswith("//", i):
            k = src.find("\n", i)
            i = n if k < 0 else k
        elif src.startswith("/*", i):
            k = src.find("*/", i + 2)
            if k < 0:
                raise ValueError("block comment never closed (line %d)" % line)
            line += src.count("\n", i, k)
            i = k + 2
        elif c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\n":
                    raise ValueError("string runs into a newline (line %d)" % line)
                if src[j] == "\\":
                    line += src[j + 1:j + 2] == "\n"
                    j += 1
                j += 1
            if j >= n:
                raise ValueError("string never closed (line %d)" % line)
            i = j + 1
            last = "id"
        elif c == "`":
            stack.append(["tpl", 0])
            i += 1
        elif c == "/" and last not in _DIVIDES_AFTER:
            j, in_class = i + 1, False
            while j < n and (in_class or src[j] != "/"):
                if src[j] == "\n":
                    raise ValueError("regex runs into a newline (line %d)" % line)
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                j += 1
            m = _WORD.match(src, j + 1)  # its flags
            i = m.end() if m else j + 1
            last = "id"
        elif c == "{":
            stack[-1][1] += 1
            i += 1
            last = ""
        elif c == "}":
            if stack[-1][1] == 0 and len(stack) > 1:
                stack.pop()  # the end of a template's ${...}
            else:
                stack[-1][1] -= 1
                last = "}"
            i += 1
        elif _WORD.match(c):
            m = _WORD.match(src, i)
            last = "" if m.group(0) in _KEYWORDS else "id"
            i = m.end()
        else:
            last = c if c in ")]" else ""
            i += 1
    if len(stack) > 1:
        raise ValueError("template literal never closed")
    return out


def strip_js(src: str) -> str:
    lines = src.split("\n")
    for ln in js_comment_lines(src):
        lines[ln - 1] = ""
    return "\n".join(lines)


def strip_css(src: str) -> str:
    """Each /* comment */ left out, all but its newlines (a space when it has none, so a comment between
    two words can't join them). Quoted strings and url(...) are passed over whole."""
    out: List[str] = []
    i, n, keep = 0, len(src), 0
    while i < n:
        c = src[i]
        if c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\n":
                    raise ValueError("string runs into a newline")
                j += 2 if src[j] == "\\" else 1
            if j >= n:
                raise ValueError("string never closed")
            i = j + 1
        elif src.startswith("url(", i) and src[i + 4:].lstrip()[:1] not in ("'", '"'):  # a quoted one is a string
            k = src.find(")", i)
            if k < 0:
                raise ValueError("url( never closed")
            i = k + 1
        elif src.startswith("/*", i):
            k = src.find("*/", i + 2)
            if k < 0:
                raise ValueError("comment never closed")
            out.append(src[keep:i])
            out.append("\n" * src.count("\n", i, k) or " ")
            i = keep = k + 2
        else:
            i += 1
    out.append(src[keep:])
    return "".join(out)


def served(name: str, body: bytes, digest: str) -> bytes:
    """What goes out for this static file at this content hash: one in NAMES without its comments, any
    other as it is. Worked out once per (name, hash); a file the scanner can't follow goes out unchanged."""
    if name not in NAMES:
        return body
    key = (name, digest)
    out = _CACHE.get(key)
    if out is None:
        try:
            text = body.decode("utf-8")
            out = (strip_css(text) if name.endswith(".css") else strip_js(text)).encode("utf-8")
        except ValueError:  # UnicodeDecodeError included: serve the file as it is
            out = body
        with _LOCK:
            if len(_CACHE) >= 64:  # old versions pile up only if files change under a running server
                _CACHE.clear()
            _CACHE[key] = out
    return out
