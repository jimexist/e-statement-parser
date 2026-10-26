"""DBS/POSB consolidated statement (deposit accounts)."""

from __future__ import annotations

import re
from decimal import Decimal

from ..models import Check, Line, Statement, mask_number
from .common import AMOUNT, money, parse_dmy, search
from .running_balance import Layout, parse_accounts

BANK = "DBS"

SUMMARY_RE = re.compile(rf"^(?:(.+?)\s+)?(\d[\d-]{{8,}}\d)\s+(?:([A-Z]{{3}})\s+)?({AMOUNT})\s+({AMOUNT})$")

LAYOUT = Layout(
    bank=BANK,
    account_header=re.compile(r"^(?:(.+?)\s+)?Account No\.?\s+([\d-]{8,})$"),
    txn_start=re.compile(r"^(\d{2}/\d{2}/\d{4})\b\s*(.*)$"),
    parse_date=parse_dmy,
    brought_forward=re.compile(rf"^Balance Brought Forward\s+(?:[A-Z]{{3}}\s+)?({AMOUNT})$", re.I),
    carried_forward=re.compile(rf"^Balance Carried Forward\s+(?:[A-Z]{{3}}\s+)?({AMOUNT})$", re.I),
    total=re.compile(
        rf"^Total Balance Carried Forward in [A-Z]{{3}}:?\s+({AMOUNT})\s+({AMOUNT})\s+({AMOUNT})$", re.I),
    noise=re.compile(
        r"^(Date\s+Description|Transaction Details as|PDS_|Page \d+ of \d+|SG\d{8,}\s+\(\d\d/\d{4}\)|w$|•)",
        re.I),
    end=re.compile(r"^(Messages For You|For Your Information)", re.I),
    currency=re.compile(r"^CURRENCY:\s*(.+)$", re.I),
    kind=lambda name: "fixed_deposit" if "fixed deposit" in name.lower() else "deposit",
    deposit_column_x=420.0,
)


def matches(text: str) -> bool:
    return ("DBS" in text or "POSB" in text) and (
        "Consolidated Statement" in text or "Balance Brought Forward" in text)


def parse(lines: list[Line]) -> Statement:
    text = "\n".join(l.text for l in lines)
    m = search(r"(?:Transaction Details|Account Summary)\s+as\s+(?:at|of)\s+(\d{1,2}\s+\w{3}\s+\d{4})", text)
    stmt = Statement(bank=BANK, statement_date=parse_dmy(m.group(1)))

    # Account Summary on page 1: closing balance of every account.
    summary: dict[str, Decimal] = {}
    for line in lines:
        t = " ".join(line.text.split())
        if LAYOUT.account_header.match(t):
            break
        if m := SUMMARY_RE.match(t):
            summary[mask_number(m.group(2))] = money(m.group(4))

    stmt.accounts = parse_accounts(lines, LAYOUT, stmt)
    parsed = {a.number_masked for a in stmt.accounts}
    for masked in summary:
        # Every account listed in the summary must show up in the details.
        stmt.checks.append(Check(f"{masked} found in transaction details", Decimal(1),
                                 Decimal(int(masked in parsed))))
    for a in stmt.accounts:
        if a.number_masked not in summary:
            continue
        if a.kind == "deposit" and a.closing_balance is not None:
            stmt.checks.append(Check(f"{a.number_masked} summary balance",
                                     summary[a.number_masked], a.closing_balance))
        elif a.closing_balance is None:
            a.closing_balance = summary[a.number_masked]
    return stmt
