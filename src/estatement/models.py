"""Bank-agnostic data model.

Sign convention for ``Transaction.amount``: from the account holder's point of
view. Money leaving you (card purchase, withdrawal) is negative; money coming
in (card payment/refund, deposit) is positive.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, computed_field

AccountKind = Literal["credit_card", "deposit", "fixed_deposit", "investment"]


class Line(BaseModel):
    """One visual line of text, as produced by an extraction backend."""

    text: str
    page: int
    y: float = 0.0
    # (x0, x1, word) for each word, when the backend knows geometry.
    words: list[tuple[float, float, str]] | None = None

    def __init__(self, text: str, page: int, **kw) -> None:
        super().__init__(text=text, page=page, **kw)


class Transaction(BaseModel):
    txn_date: date
    description: str
    amount: Decimal
    post_date: date | None = None
    reference: str | None = None
    balance: Decimal | None = None
    page: int | None = None

    def natural_key(self, account_key: str) -> str:
        """Stable id so re-importing the same statement is idempotent."""
        parts = [
            account_key,
            self.txn_date.isoformat(),
            self.post_date.isoformat() if self.post_date else "",
            self.reference or self.description,
            str(self.amount),
            str(self.balance) if self.balance is not None else "",
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


class Account(BaseModel):
    bank: str
    kind: AccountKind
    name: str
    number_masked: str
    currency: str = "SGD"
    holder: str | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    transactions: list[Transaction] = Field(default_factory=list)

    @computed_field
    @property
    def key(self) -> str:
        return f"{self.bank}:{self.kind}:{self.number_masked}"


class Check(BaseModel):
    name: str
    expected: Decimal
    actual: Decimal
    # False for bookkeeping counters (e.g. "0 errors") that can pass vacuously.
    against_printed_total: bool = True

    def __init__(self, name: str, expected: Decimal, actual: Decimal, **kw) -> None:
        super().__init__(name=name, expected=expected, actual=actual, **kw)

    @computed_field
    @property
    def ok(self) -> bool:
        return self.expected == self.actual


class Statement(BaseModel):
    bank: str
    statement_date: date
    accounts: list[Account] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    # Statement-level facts (amount due, due date, ...) as strings.
    meta: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def ok(self) -> bool:
        # Reconciled only if at least one printed total was actually compared.
        return (
            bool(self.accounts)
            and any(c.against_printed_total for c in self.checks)
            and all(c.ok for c in self.checks)
        )

    def transactions(self) -> Iterator[tuple[Account, Transaction]]:
        for acct in self.accounts:
            for t in acct.transactions:
                yield acct, t


def mask_number(number: str) -> str:
    """Keep only the last four digits of a card/account number."""
    digits = "".join(ch for ch in number if ch.isdigit())
    return f"****{digits[-4:]}"
