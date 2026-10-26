"""Shared engine for deposit-account statements that print a running balance.

Each transaction is a block: a line starting with a date, followed by
description lines. The amounts (``amount balance`` or just ``balance``) may be
on the date line (text layer) or on a later line (OCR/VLM output). The sign is
taken from the change in running balance, which doubles as a per-row check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable

from ..models import Account, Check, Line, Statement, Transaction, mask_number
from .common import AMOUNT, AMOUNT_RE, money

TRAILING_AMOUNTS_RE = re.compile(rf"^(.*?)\s*((?:{AMOUNT}\s*){{1,2}})$")


@dataclass
class Layout:
    bank: str
    account_header: re.Pattern   # groups: name (may be None: taken from previous line), number
    txn_start: re.Pattern        # groups: date text, rest of line
    parse_date: Callable[[str], date]
    brought_forward: re.Pattern  # group: amount
    total: re.Pattern | None = None            # groups: withdrawn, deposited, closing
    carried_forward: re.Pattern | None = None  # group: amount
    noise: re.Pattern | None = None
    end: re.Pattern | None = None
    currency: re.Pattern | None = None         # group: currency name
    kind: Callable[[str], str] = lambda name: "deposit"
    # x (points) left of which an amount is a withdrawal; only consulted when
    # the running balance cannot decide.
    deposit_column_x: float | None = None


def parse_accounts(lines: list[Line], layout: Layout, stmt: Statement) -> list[Account]:
    accounts: dict[str, Account] = {}
    sums: dict[str, list[Decimal]] = {}
    acct: Account | None = None
    running: Decimal | None = None
    block: tuple[str, list[tuple[str, Line]]] | None = None
    errors = 0

    def flush():
        nonlocal block, running, errors
        if block is None:
            return
        day, items = block
        block = None
        desc, amounts, amount_line = [], None, None
        for text, src in items:
            m = TRAILING_AMOUNTS_RE.match(text)
            if amounts is None and m:
                amounts = [money(a) for a in AMOUNT_RE.findall(m.group(2))]
                amount_line, text = src, m.group(1)
            if text:
                desc.append(text)
        if not amounts:
            stmt.warnings.append(f"{acct.number_masked}: no amount for {day} {' '.join(desc)[:40]}")
            errors += 1
            return
        balance = amounts[-1]
        amount = amounts[0] if len(amounts) >= 2 else None
        if running is None:
            stmt.warnings.append(f"{acct.number_masked}: transaction before opening balance")
            running = balance
        delta = balance - running
        if amount is None:
            amount = abs(delta)
        if amount == 0:
            return  # balance-only row
        if abs(delta) == amount:
            signed = delta
        else:
            errors += 1
            signed = amount if _deposit_column(amount_line, layout) else -amount
        running = balance
        sums[acct.number_masked][0 if signed < 0 else 1] += amount
        acct.transactions.append(Transaction(
            txn_date=layout.parse_date(day), description=" | ".join(desc), amount=signed,
            balance=balance, page=items[0][1].page))

    prev = ""
    for line in lines:
        t = " ".join(line.text.split())
        if layout.end and layout.end.search(t):
            break
        last_line, prev = prev, t
        if m := layout.account_header.match(t):
            flush()
            # OCR may put the account name on the line above "Account No. ...".
            name, number = (m.group(1) or last_line).strip(), m.group(2)
            masked = mask_number(number)
            if masked not in accounts:
                accounts[masked] = Account(bank=layout.bank, kind=layout.kind(name),
                                           name=name, number_masked=masked)
                sums[masked] = [Decimal(0), Decimal(0)]
            acct = accounts[masked]
            continue
        if acct is None or (layout.noise and layout.noise.match(t)):
            continue
        if layout.currency and (m := layout.currency.match(t)):
            acct.currency = {"SINGAPORE DOLLAR": "SGD"}.get(m.group(1).upper(), m.group(1))
            continue
        if acct.kind != "deposit":
            continue  # e.g. fixed deposit tables: different layout, balance comes from summary
        if m := layout.brought_forward.match(t):
            flush()
            running = money(m.group(1))
            if acct.opening_balance is None:
                acct.opening_balance = running
            continue
        if layout.carried_forward and (m := layout.carried_forward.match(t)):
            flush()
            if running is not None and money(m.group(1)) != running:
                errors += 1
            continue
        if layout.total and (m := layout.total.match(t)):
            flush()
            withdrawn, deposited, closing = (money(g) for g in m.groups())
            acct.closing_balance = closing
            w, d = sums[acct.number_masked]
            stmt.checks += [
                Check(f"{acct.number_masked} total withdrawals", withdrawn, w),
                Check(f"{acct.number_masked} total deposits", deposited, d),
                Check(f"{acct.number_masked} closing balance", closing,
                      running if running is not None else Decimal(0)),
            ]
            continue
        if m := layout.txn_start.match(t):
            flush()
            block = (m.group(1), [(m.group(2), line)])
            continue
        if block is not None:
            block[1].append((t, line))
    flush()

    stmt.checks.append(Check("running balance errors", Decimal(0), Decimal(errors),
                             against_printed_total=False))
    for a in accounts.values():
        if a.kind != "deposit":
            continue
        if layout.total and a.closing_balance is None:
            # Never report "reconciled" without having compared against a printed total.
            stmt.checks.append(Check(f"{a.number_masked} printed total found", Decimal(1), Decimal(0)))
        if a.closing_balance is None and a.transactions:
            a.closing_balance = a.transactions[-1].balance
    return list(accounts.values())


def _deposit_column(line: Line | None, layout: Layout) -> bool:
    if line is None or not line.words or layout.deposit_column_x is None:
        return False
    nums = [w for w in line.words if AMOUNT_RE.fullmatch(w[2])]
    return len(nums) >= 2 and nums[-2][0] > layout.deposit_column_x
