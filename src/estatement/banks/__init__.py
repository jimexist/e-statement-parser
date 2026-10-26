"""Per-bank layout rules. Each module exposes ``matches(text)`` and ``parse(lines)``.

To add a bank: write a module with those two functions and append it to PARSERS.
"""

from __future__ import annotations

from ..models import Line, Statement
from . import dbs, hsbc_cc, uob_cc, uob_deposit

PARSERS = [uob_cc, uob_deposit, dbs, hsbc_cc]


class UnknownBank(ValueError):
    pass


def detect(lines: list[Line]):
    text = "\n".join(l.text for l in lines)
    for mod in PARSERS:
        if mod.matches(text):
            return mod
    raise UnknownBank("no parser recognises this statement")


def parse_lines(lines: list[Line]) -> Statement:
    return detect(lines).parse(lines)
