"""UOB credit card statement."""

from __future__ import annotations

import re
from decimal import Decimal

from ..models import Account, Check, Line, Statement, Transaction, mask_number
from .common import AMOUNT, DAY_MON, day_month, money, parse_dmy, require, search

BANK = "UOB"

DM = DAY_MON
TXN_RE = re.compile(rf"^({DM})\s+({DM})\s+(.+?)\s+({AMOUNT})\s*(CR)?$")
REF_RE = re.compile(r"^Ref\s*No\.?\s*:?\s*(\d{6,})$", re.I)
# Card section header: "1111-2222-3333-4444 TAN AH KOW (continued)". Layout
# models sometimes glue the name to the number or append column headers.
CARD_HEADER_RE = re.compile(
    r"^(\d{4}-\d{4}-\d{4}-\d{4})\s*([A-Z][A-Z .'-]*?)(?:\s*\(continued\)|\s+-\s+\D*)?$"
)
INLINE_REF_RE = re.compile(r"\s*Ref\s*No\.?\s*:?\s*(\d{6,})\s*")
PREV_RE = re.compile(rf"^PREVIOUS BALANCE\s+({AMOUNT})\s*(CR)?$")
SUBTOTAL_RE = re.compile(rf"^SUB TOTAL\s+({AMOUNT})\s*(CR)?$")
TOTAL_RE = re.compile(rf"^TOTAL BALANCE FOR .+?\s+({AMOUNT})\s*(CR)?$")
END_RE = re.compile(r"End of Transaction Details", re.I)


def matches(text: str) -> bool:
    return "uobgroup.com" in text.lower() and "Credit Card(s) Statement" in text


def _signed(amount: str, cr: str | None) -> Decimal:
    """Balance-owed convention: CR reduces what you owe."""
    return -money(amount) if cr else money(amount)


def parse(lines: list[Line]) -> Statement:
    text = "\n".join(l.text for l in lines)
    stmt_date = parse_dmy(
        require(r"Statement Date\s+(\d{1,2}\s+[A-Z]{3}\s+\d{4})", text, "statement date").group(1)
    )
    stmt = Statement(bank=BANK, statement_date=stmt_date)
    for key, pat in {
        "amount_to_pay": rf"Amount to Pay\s+SGD\s+({AMOUNT})",
        "minimum_payment": rf"Minimum Payment\s+SGD\s+({AMOUNT})",
        "due_date": r"Due Date\s+(\d{1,2}\s+[A-Z]{3}\s+\d{4})",
        "credit_limit": r"Total Credit Limit\s+SGD\s+([\d,]+)",
    }.items():
        if m := search(pat, text):
            stmt.meta[key] = m.group(1)
    if "due_date" in stmt.meta:
        stmt.meta["due_date"] = parse_dmy(stmt.meta["due_date"]).isoformat()

    acct: Account | None = None
    accounts: dict[str, Account] = {}
    subtotals: dict[str, Decimal] = {}
    totals: dict[str, Decimal] = {}
    last: Transaction | None = None
    prev_text = ""
    for line in lines:
        t = line.text.strip()
        if END_RE.search(t):
            break
        if m := CARD_HEADER_RE.match(t):
            number, holder = m.groups()
            masked = mask_number(number)
            if masked not in accounts:
                accounts[masked] = Account(
                    bank=BANK,
                    kind="credit_card",
                    name=prev_text or "UOB CARD",
                    number_masked=masked,
                    holder=holder.strip(),
                )
            acct = accounts[masked]
            last = None
        elif acct is None:
            pass
        elif m := PREV_RE.match(t):
            acct.opening_balance = _signed(*m.groups())
        elif m := TXN_RE.match(t):
            post, trans, desc, amount, cr = m.groups()
            ref = None
            if r := INLINE_REF_RE.search(desc):
                ref, desc = r.group(1), INLINE_REF_RE.sub(" ", desc)
            last = Transaction(
                post_date=day_month(post, stmt_date),
                txn_date=day_month(trans, stmt_date),
                description=" ".join(desc.split()),
                # Holder's view: purchases are outflows (negative).
                amount=-_signed(amount, cr),
                reference=ref,
                page=line.page,
            )
            acct.transactions.append(last)
        elif (m := REF_RE.match(t)) and last is not None:
            last.reference = m.group(1)
        elif m := SUBTOTAL_RE.match(t):
            subtotals[acct.number_masked] = _signed(*m.groups())
        elif m := TOTAL_RE.match(t):
            totals[acct.number_masked] = _signed(*m.groups())
            acct.closing_balance = totals[acct.number_masked]
        prev_text = t

    stmt.accounts = list(accounts.values())
    for a in stmt.accounts:
        # Each card must be checked opening + transactions against a printed total;
        # a missing anchor is a failure, never a silent skip.
        printed = subtotals.get(a.number_masked, a.closing_balance)
        if a.opening_balance is None or printed is None:
            stmt.checks.append(
                Check(f"{a.number_masked} previous balance and total found", Decimal(1), Decimal(0))
            )
            continue
        computed = a.opening_balance - sum((t.amount for t in a.transactions), Decimal(0))
        if a.number_masked in subtotals:
            stmt.checks.append(Check(f"{a.number_masked} sub total", subtotals[a.number_masked], computed))
        if a.closing_balance is not None:
            stmt.checks.append(Check(f"{a.number_masked} total balance", a.closing_balance, computed))
    if "amount_to_pay" in stmt.meta and stmt.accounts:
        stmt.checks.append(
            Check(
                "amount to pay = sum of card balances",
                money(stmt.meta["amount_to_pay"]),
                sum((a.closing_balance or Decimal(0) for a in stmt.accounts), Decimal(0)),
            )
        )
    if not stmt.accounts:
        stmt.warnings.append("no card sections found")
    return stmt
