"""Turn markdown/HTML emitted by layout models and VLMs into plain lines.

Table rows become one line with the non-empty cells joined by spaces, which
matches what the text-layer backend produces for the same row.
"""

from __future__ import annotations

import html
import re

from ..models import Line

_TAG_RE = re.compile(r"<[^>]+>")
_SEP_RE = re.compile(r"^\|?\s*:?-{3,}")


def to_lines(markdown: str, page: int) -> list[Line]:
    out: list[Line] = []
    text = markdown.replace("\r", "")
    # HTML tables: one line per row, cells space-joined.
    text = re.sub(r"</t[dh]>\s*", " ", text, flags=re.I)
    text = re.sub(r"</tr>|<br\s*/?>", "\n", text, flags=re.I)
    for raw in text.split("\n"):
        s = raw.strip()
        if not s or s.startswith("<!--") or _SEP_RE.match(s):
            continue
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            s = " ".join(c for c in cells if c)
        s = html.unescape(_TAG_RE.sub(" ", s))
        s = re.sub(r"^#+\s*|^[-*]\s+|\*\*", "", s)
        s = " ".join(s.split())
        if s:
            out.append(Line(text=s, page=page, y=float(len(out))))
    return out
