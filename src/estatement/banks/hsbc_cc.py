"""HSBC Singapore credit card statement.

These PDFs have no text layer (glyphs are drawn as vector paths), so lines
come from an OCR backend.
"""

from __future__ import annotations

import re
from decimal import Decimal

from ..models import Account, Check, Line, Statement, Transaction, mask_number
from .common import AMOUNT, DAY_MON, day_month, money, parse_dmy, require, search

BANK = "HSBC"

DM = DAY_MON
TXN_RE = re.compile(rf"^({DM})\s+({DM})\s+(.+?)\s+({AMOUNT})\s*(CR)?$", re.I)
CARD_RE = re.compile(r"^([A-Za-z][A-Za-z .'-]*?)\s+(\d{4}-[\dX]{4}-[\dX]{4}-\d{4})$")
PREV_RE = re.compile(rf"^Previous Statement Balance\s+({AMOUNT})\s*(CR)?$", re.I)
END_RE = re.compile(r"^Total Due\b", re.I)


def matches(text: str) -> bool:
    return "HSBC" in text and "Statement period" in text


def _owed(amount: str, cr: str | None) -> Decimal:
    return -money(amount) if cr else money(amount)


def parse(lines: list[Line]) -> Statement:
    text = "\n".join(l.text for l in lines)
    period_end = require(
        r"From\s+\d{1,2}\s+\w{3}\s+\d{4}\s+to\s+(\d{1,2}\s+\w{3}\s+\d{4})", text, "statement period"
    )
    stmt = Statement(bank=BANK, statement_date=parse_dmy(period_end.group(1)))
    for key, pat in {
        "amount_to_pay": rf"Total Due\s+({AMOUNT})",
        "minimum_payment": rf"Minimum Payment\s+({AMOUNT})",
        "due_date": r"Payment Due Date\s+(\d{1,2}\s+\w{3}\s+\d{4})",
        "credit_limit": rf"Credit Limit \(SGD\)\s+({AMOUNT})",
    }.items():
        if m := search(pat, text):
            stmt.meta[key] = m.group(1)
    if "due_date" in stmt.meta:
        stmt.meta["due_date"] = parse_dmy(stmt.meta["due_date"]).isoformat()

    accounts: dict[str, Account] = {}
    acct: Account | None = None
    opening: Decimal | None = None
    last: Transaction | None = None
    for line in lines:
        t = " ".join(line.text.split())
        if m := CARD_RE.match(t):
            holder, number = m.groups()
            masked = mask_number(number)
            acct = accounts.setdefault(
                masked,
                Account(bank=BANK, kind="credit_card", name="HSBC CARD", number_masked=masked, holder=holder),
            )
            last = None
        elif acct is None:
            continue
        elif END_RE.match(t):
            acct, last = None, None
        elif m := PREV_RE.match(t):
            opening = _owed(*m.groups())
        elif m := TXN_RE.match(t):
            post, trans, desc, amount, cr = m.groups()
            last = Transaction(
                post_date=day_month(post, stmt.statement_date),
                txn_date=day_month(trans, stmt.statement_date),
                description=" ".join(desc.split()),
                amount=-_owed(amount, cr),
                page=line.page,
            )
            acct.transactions.append(last)
        elif last is not None and not search(AMOUNT, t):
            # Wrapped description, e.g. the country code on its own line.
            last.description += " " + t
    stmt.accounts = list(accounts.values())

    debits = sum((-t.amount for _, t in stmt.transactions() if t.amount < 0), Decimal(0))
    credits = sum((t.amount for _, t in stmt.transactions() if t.amount > 0), Decimal(0))
    for name, pat, actual in [
        ("purchases & debits", rf"Purchases & Debits\s+({AMOUNT})\s*(CR)?", debits),
        ("payments & credits", rf"Payments & Credits\s+({AMOUNT})\s*(CR)?", -credits),
    ]:
        if m := search(pat, text):
            stmt.checks.append(Check(name, _owed(*m.groups()), actual))
    m = search(rf"Total Account Balance(?:\s*\(incl GST\))?\s+({AMOUNT})\s*(CR)?", text)
    if m and opening is not None:
        closing = _owed(*m.groups())
        stmt.checks.append(Check("total account balance", closing, opening + debits - credits))
        if len(stmt.accounts) == 1:
            stmt.accounts[0].opening_balance, stmt.accounts[0].closing_balance = opening, closing
    else:
        stmt.checks.append(Check("previous and total account balance found", Decimal(1), Decimal(0)))
    if not stmt.accounts:
        stmt.warnings.append("no card section found")
    return stmt
