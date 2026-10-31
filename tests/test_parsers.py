from datetime import date
from decimal import Decimal

import pymupdf
import pytest
from synthetic import UOB_CC_LINES, lines, uob_cc_joined

from estatement.backends.markdown import to_lines
from estatement.backends.textlayer import extract_lines
from estatement.banks import UnknownBank, parse_lines, uob_cc
from estatement.banks.common import ParseError, day_month
from estatement.models import Line
from estatement.pipeline import parse_pdf


def test_year_inference_rolls_back_over_new_year():
    assert day_month("30 DEC", date(2027, 1, 6)) == date(2026, 12, 30)
    assert day_month("02 JAN", date(2027, 1, 6)) == date(2027, 1, 2)
    assert day_month("05 Sep", date(2026, 10, 6)) == date(2026, 9, 5)


def test_uob_cc_reconciles_and_signs():
    stmt = uob_cc.parse(lines(uob_cc_joined()))
    assert stmt.ok, [(c.name, c.expected, c.actual) for c in stmt.checks]
    (acct,) = stmt.accounts
    assert acct.number_masked == "****4444"
    assert acct.holder == "TEST USER"
    amounts = [t.amount for t in acct.transactions]
    assert amounts == [Decimal("200.00"), Decimal("-1.50"), Decimal("-99.00"), Decimal("-20.00")]
    assert acct.transactions[0].reference is None
    # Statement dated 06 OCT 2026: "30 DEC" must be 2025, not 2026.
    assert acct.transactions[-1].txn_date == date(2025, 12, 30)
    assert acct.transactions[-1].post_date == date(2026, 1, 2)
    coffee = next(t for t in acct.transactions if "COFFEE" in t.description)
    assert coffee.reference == "00000000000000000000002"
    assert stmt.meta["due_date"] == "2026-10-27"


def test_uob_cc_amount_on_its_own_line_is_not_lost():
    # "BUS/MRT ... 1.50" split over lines must not silently drop the amount:
    # the reconciliation check catches it.
    stmt = uob_cc.parse(lines(UOB_CC_LINES))
    assert not stmt.ok


def test_full_card_number_never_stored():
    stmt = uob_cc.parse(lines(UOB_CC_LINES))
    assert all("1111" not in a.number_masked for a in stmt.accounts)


def test_markdown_tables_flatten_to_rows():
    md = """
| Post Date | Trans Date | Description | Amount |
|---|---|---|---|
| 07 SEP | 02 SEP | BUS/MRT 1 SINGAPORE Ref No. : 00000000000000000000001 | 1.50 |

## 1111-2222-3333-4444TAN TEST (continued)
<table><tr><td>08 SEP</td><td>04 SEP</td><td>SHOP</td><td>2.00 CR</td></tr></table>
"""
    texts = [l.text for l in to_lines(md, page=1)]
    assert "07 SEP 02 SEP BUS/MRT 1 SINGAPORE Ref No. : 00000000000000000000001 1.50" in texts
    assert "08 SEP 04 SEP SHOP 2.00 CR" in texts
    assert "1111-2222-3333-4444TAN TEST (continued)" in texts


def test_unknown_bank_is_rejected():
    with pytest.raises(UnknownBank):
        parse_lines([Line("hello world", 1)])


def _deposit_lines(split_amounts: bool) -> list[Line]:
    rows = [
        ("01/09/2026", ["Advice FAST Payment / Receipt", "SALARY PAYMENT"], "5,000.00", "6,000.00"),
        ("03/09/2026", ["Advice FAST Payment / Receipt", "RENT"], "2,300.00", "3,700.00"),
    ]
    out = [
        "Consolidated Statement",
        "Transaction Details as at 30 Sep 2026",
        "Savings Account Account No. 000-000001-0",
        "Balance Brought Forward SGD 1,000.00",
    ]
    for day, desc, amt, bal in rows:
        if split_amounts:  # VLM style: description joined, amounts on next line
            out += [f"{day} {' '.join(desc)}", f"{amt} {bal}"]
        else:  # text-layer style: amounts on the date line
            out += [f"{day} {desc[0]} {amt} {bal}", *desc[1:]]
    out += ["Total Balance Carried Forward in SGD: 2,300.00 5,000.00 3,700.00", "DBS"]
    return lines("\n".join(out))


@pytest.mark.parametrize("split", [False, True])
def test_running_balance_engine_handles_both_layouts(split):
    stmt = parse_lines(_deposit_lines(split))
    assert stmt.bank == "DBS"
    assert stmt.ok, [(c.name, c.expected, c.actual) for c in stmt.checks]
    t1, t2 = stmt.accounts[0].transactions
    assert (t1.amount, t2.amount) == (Decimal("5000.00"), Decimal("-2300.00"))
    assert "SALARY PAYMENT" in t1.description


def test_running_balance_detects_misread_amount():
    ls = _deposit_lines(False)
    i = next(i for i, l in enumerate(ls) if "2,300.00 3,700.00" in l.text)
    ls[i] = Line(ls[i].text.replace("2,300.00 3,700.00", "2,800.00 3,700.00"), 1)
    stmt = parse_lines(ls)
    assert not stmt.ok


def test_textlayer_end_to_end_on_generated_pdf(tmp_path):
    """Write a synthetic UOB-style PDF, read it back through the text layer."""
    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    for text in (uob_cc_joined() + "card.centre@uobgroup.com").splitlines():
        page.insert_text((40, y), text, fontsize=8)
        y += 14
    pdf = tmp_path / "synthetic.pdf"
    doc.save(pdf)
    assert extract_lines(pdf)[0].text == "Statement Date 06 OCT 2026"
    stmt = parse_pdf(pdf)
    assert stmt.meta["backend"] == "textlayer"
    assert stmt.ok, [(c.name, c.expected, c.actual) for c in stmt.checks]
    assert len(stmt.accounts[0].transactions) == 4


def test_missing_statement_date_is_a_clear_error():
    with pytest.raises(ParseError, match="statement date"):
        uob_cc.parse(lines("Credit Card(s) Statement\nuobgroup.com"))


UOB_FX_LINES = """\
Statement of Account
Period: 01 Sep 2026 to 30 Sep 2026
One Account 000-000-000-1
Date Description Withdrawals Deposits Balance
SGD SGD SGD
01 Sep BALANCE B/F 100.00
09 Sep Currency Conversion 1,264.40 1,364.40
USD 1000.00
Total 0.00 1,264.40 1,364.40
FX+ 000-000-000-2
Date Description Withdrawals Deposits Balance
AUD AUD AUD
01 Sep BALANCE B/F 0.00
Total 0.00
FX+ 000-000-000-3
Date Description Withdrawals Deposits Balance
USD USD USD
01 Sep BALANCE B/F 1,000.50
09 Sep Currency Conversion 1,000.00 0.50
USD/SGD@1.2644
Total 1,000.00 0.00 0.50
End of Transaction Details
www.uobgroup.com
"""


def test_uob_fx_wallets_are_separate_accounts():
    stmt = parse_lines(lines(UOB_FX_LINES))
    assert stmt.ok, [(c.name, c.expected, c.actual) for c in stmt.checks]
    # The unused AUD wallet is dropped; SGD and USD keep their own balances.
    sgd, usd = stmt.accounts
    assert (sgd.number_masked, sgd.currency, sgd.closing_balance) == ("****0001", "SGD", Decimal("1364.40"))
    assert (usd.number_masked, usd.currency, usd.closing_balance) == ("****0003", "USD", Decimal("0.50"))
    assert [t.amount for t in usd.transactions] == [Decimal("-1000.00")]
