"""Show where one backend diverges from ground truth, with every digit masked.

uv run python eval/debug.py uob_one_2026-09 "C1 GLM"
"""

import json
import re
import sys

from compare import BACKENDS, STATEMENTS, TRUTH, extract_cached, rows_of

from estatement.banks import parse_lines


def mask(s):
    return re.sub(r"\d", "#", str(s))


stem, which = sys.argv[1], sys.argv[2]
label = next(l for l in BACKENDS if which.lower() in l.lower())
lines, secs, err = extract_cached(STATEMENTS / f"{stem}.pdf", label, False)
truth = json.loads((TRUTH / f"{stem}.json").read_text())["transactions"]
stmt = parse_lines(lines)
pred = rows_of(stmt)
print("checks:", [(c.name, c.ok) for c in stmt.checks])
print("warnings:", [mask(w) for w in stmt.warnings])


def key(r):
    return (r["account"], r["txn_date"], r["amount"])


pk = [key(p) for p in pred]
for t in truth:
    if key(t) in pk:
        pk.remove(key(t))
    else:
        print("MISSING", mask(t["txn_date"]), mask(t["description"])[:80])
if "--lines" in sys.argv:
    for l in lines:
        print(l.page, mask(l.text)[:140])
