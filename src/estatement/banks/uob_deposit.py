"""UOB deposit account "Statement of Account" (e.g. One Account)."""

from __future__ import annotations

import re

from ..models import Line, Statement
from .common import AMOUNT, DAY_MON, day_month, parse_dmy, require
from .running_balance import Layout, parse_accounts

BANK = "UOB"


def matches(text: str) -> bool:
    return "uobgroup.com" in text.lower() and "Statement of Account" in text


def parse(lines: list[Line]) -> Statement:
    text = "\n".join(l.text for l in lines)
    m = require(
        r"Period:\s*\d{1,2}\s+\w{3}\s+\d{4}\s+to\s+(\d{1,2}\s+\w{3}\s+\d{4})", text, "statement period"
    )
    stmt = Statement(bank=BANK, statement_date=parse_dmy(m.group(1)))
    layout = Layout(
        bank=BANK,
        # "FX+ 123-456-789-0" heads each foreign-currency wallet, each with its own number.
        account_header=re.compile(r"^(.+?Account|FX\+)\s+(\d{3}-\d{3}-\d{3}-\d)(?:\s*\(continued\))?$"),
        # "05 Sep ..." starts a row; "04 SEP 2026 1234567" (card txn date) is a continuation.
        txn_start=re.compile(rf"^({DAY_MON})(?!\s+\d{{4}})\s+(.*)$"),
        parse_date=lambda s: day_month(s, stmt.statement_date),
        brought_forward=re.compile(rf"^(?:\d{{2}}\s+[A-Za-z]{{3}}\s+)?BALANCE B/F\s+({AMOUNT})$", re.I),
        # An untouched currency wallet prints only "Total 0.00".
        total=re.compile(rf"^Total\s+(?:({AMOUNT})\s+({AMOUNT})\s+)?({AMOUNT})$"),
        noise=re.compile(r"^(Date\s+Description|Page \d+ of \d+|Account Transaction Details)", re.I),
        end=re.compile(r"End of Transaction Details", re.I),
        currency=re.compile(r"^([A-Z]{3})\s+\1\s+\1$"),
        deposit_column_x=430.0,
    )
    stmt.accounts = parse_accounts(lines, layout, stmt)
    return stmt
