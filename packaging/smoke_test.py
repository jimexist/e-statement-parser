"""Smoke-test a built eStatement.app with a synthetic statement (no personal data).

uv run python packaging/smoke_test.py dist/eStatement.app
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from synthetic import uob_cc_joined


def main(app: Path) -> int:
    exe = app / "Contents" / "MacOS" / "eStatement"
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "synthetic.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        for i, text in enumerate((uob_cc_joined() + "card.centre@uobgroup.com").splitlines()):
            page.insert_text((40, 60 + 14 * i), text, fontsize=8)
        doc.save(pdf)
        out = subprocess.run(
            [str(exe), "parse", str(pdf), "--backend", "textlayer"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        print(out.stderr)
        rows = out.stdout.strip().splitlines()
        assert out.returncode == 0, f"exit {out.returncode}"
        assert "reconciled" in out.stderr and "NOT" not in out.stderr, "statement did not reconcile"
        assert len(rows) == 5, f"expected header + 4 rows, got {len(rows)}"
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
