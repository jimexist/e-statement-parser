"""Regression tests against your own statements in data/ (gitignored).

Skipped when the files aren't present, so the suite runs anywhere.
"""

import json
from pathlib import Path

import pytest

from estatement.backends.textlayer import has_text_layer
from estatement.pipeline import parse_pdf

DATA = Path(__file__).resolve().parent.parent / "data"
CASES = sorted((DATA / "ground_truth").glob("*.json")) if (DATA / "ground_truth").exists() else []


@pytest.mark.parametrize("gt", CASES, ids=[p.stem for p in CASES])
def test_matches_ground_truth(gt):
    pdf = DATA / "statements" / f"{gt.stem}.pdf"
    if not pdf.exists():
        pytest.skip("statement not present")
    if not has_text_layer(pdf):
        pytest.skip("image-only PDF needs the OCR model; covered by eval/compare.py")
    truth = json.loads(gt.read_text())["transactions"]
    stmt = parse_pdf(pdf)
    assert stmt.ok
    got = [(a.key, t.txn_date.isoformat(), str(t.amount), t.description, t.reference)
           for a, t in stmt.transactions()]
    want = [(t["account"], t["txn_date"], t["amount"], t["description"], t["reference"]) for t in truth]
    assert got == want
