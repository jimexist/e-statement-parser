from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

AMOUNT = r"\d{1,3}(?:,\d{3})*\.\d{2}"
# "05 SEP" / "05 Sep": only real month names, so OCR noise can't reach day_month().
DAY_MON = r"\d{2}\s+(?i:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
AMOUNT_RE = re.compile(AMOUNT)
MONTHS = {
    m: i
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1
    )
}


def money(s: str) -> Decimal:
    return Decimal(s.replace(",", "").replace(" ", ""))


def parse_dmy(s: str) -> date:
    """'06 OCT 2026', '30 Sep 2026' or '30/09/2026'."""
    s = " ".join(s.split())
    for fmt in ("%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.title(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unrecognised date {s!r}")


def day_month(s: str, statement_date: date) -> date:
    """'01 SEP' with no year: pick the year so the date is not after the statement."""
    day, mon = s.split()
    month = MONTHS[mon.upper()[:3]]
    year = statement_date.year - (1 if month > statement_date.month else 0)
    return date(year, month, int(day))


class ParseError(ValueError):
    """The statement is missing something the layout requires."""


def search(pattern: str, text: str, flags: int = re.I) -> re.Match | None:
    return re.search(pattern, text, flags)


def require(pattern: str, text: str, what: str, flags: int = re.I) -> re.Match:
    if m := re.search(pattern, text, flags):
        return m
    raise ParseError(f"could not find {what}")
