"""Synthetic statements (fake data) for tests and UI demos."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from estatement.models import Account, Check, Line, Statement, Transaction

UOB_CC_LINES = """\
Statement Date 06 OCT 2026
Total Credit Limit SGD 10,000
Amount to Pay SGD 120.50
Minimum Payment SGD 50.00
Credit Card(s) Statement Due Date 27 OCT 2026
UOB ONE CARD 1111-2222-3333-4444 TEST USER 120.50 50.00
UOB ONE CARD
1111-2222-3333-4444 TEST USER
Post Trans Description of Transaction Transaction Amount
PREVIOUS BALANCE 200.00
08 SEP 08 SEP PAYMT THRU E-BANK/HOMEB/CYBERB (EP57) 200.00 CR
07 SEP 02 SEP BUS/MRT 000000001 SINGAPORE
Ref No. : 00000000000000000000001
1.50
08 SEP 04 SEP COFFEE SHOP SINGAPORE 99.00
Ref No. : 00000000000000000000002
1111-2222-3333-4444 TEST USER (continued)
02 JAN 30 DEC LATE YEAR MERCHANT SINGAPORE 20.00
Ref No. : 00000000000000000000003
SUB TOTAL 120.50
TOTAL BALANCE FOR UOB ONE CARD 120.50
End of Transaction Details
"""


def uob_cc_joined(text: str = UOB_CC_LINES) -> str:
    """Same statement with every amount on its row, as a text layer produces it."""
    return text.replace(
        "BUS/MRT 000000001 SINGAPORE\nRef No. : 00000000000000000000001\n1.50",
        "BUS/MRT 000000001 SINGAPORE 1.50\nRef No. : 00000000000000000000001",
    )


def lines(text: str) -> list[Line]:
    return [Line(text=t, page=1, y=float(i)) for i, t in enumerate(text.splitlines()) if t.strip()]


def demo_statements() -> list[Statement]:
    card = Account(
        bank="UOB",
        kind="credit_card",
        name="UOB ONE CARD",
        number_masked="****4444",
        holder="TEST USER",
        opening_balance=Decimal("200.00"),
        closing_balance=Decimal("140.40"),
    )
    card.transactions = [
        Transaction(
            txn_date=date(2026, 9, 8),
            description="PAYMT THRU E-BANK",
            amount=Decimal("200.00"),
            post_date=date(2026, 9, 8),
        ),
        Transaction(
            txn_date=date(2026, 9, 2),
            description="BUS/MRT 000000001 SINGAPORE",
            amount=Decimal("-1.50"),
            post_date=date(2026, 9, 7),
            reference="00000000000000000000001",
        ),
        Transaction(
            txn_date=date(2026, 9, 4),
            description="COFFEE SHOP SINGAPORE",
            amount=Decimal("-6.40"),
            post_date=date(2026, 9, 8),
            reference="00000000000000000000002",
        ),
        Transaction(
            txn_date=date(2026, 9, 12),
            description="SUPERMARKET DEMO",
            amount=Decimal("-82.35"),
            post_date=date(2026, 9, 14),
            reference="00000000000000000000003",
        ),
        Transaction(
            txn_date=date(2026, 9, 20),
            description="BOOKSTORE SINGAPORE",
            amount=Decimal("-50.15"),
            post_date=date(2026, 9, 22),
            reference="00000000000000000000004",
        ),
    ]
    savings = Account(
        bank="DBS",
        kind="deposit",
        name="Savings Account",
        number_masked="****0001",
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("3700.00"),
    )
    savings.transactions = [
        Transaction(
            txn_date=date(2026, 9, 1),
            description="Advice FAST Payment / Receipt | SALARY PAYMENT",
            amount=Decimal("5000.00"),
            balance=Decimal("6000.00"),
        ),
        Transaction(
            txn_date=date(2026, 9, 3),
            description="Advice FAST Payment / Receipt | PAYNOW TRANSFER | RENT",
            amount=Decimal("-2300.00"),
            balance=Decimal("3700.00"),
        ),
    ]
    a = Statement(
        bank="UOB",
        statement_date=date(2026, 10, 6),
        accounts=[card],
        checks=[Check("****4444 total balance", Decimal("140.40"), Decimal("140.40"))],
        meta={"backend": "textlayer"},
    )
    b = Statement(
        bank="DBS",
        statement_date=date(2026, 9, 30),
        accounts=[savings],
        checks=[Check("****0001 closing balance", Decimal("3700.00"), Decimal("3700.00"))],
        meta={"backend": "textlayer"},
    )
    return [a, b]


if __name__ == "__main__":
    import sys

    from estatement.store import Store

    store = Store(sys.argv[1])
    for i, s in enumerate(demo_statements()):
        store.save(s, f"demo{i}", f"demo-{s.bank.lower()}.pdf")
    print("demo db written to", sys.argv[1])
