# eStatement

Turns bank and credit-card e-statement PDFs into a SQLite database and CSV, for
household bookkeeping. **Everything runs on your Mac**: no cloud APIs, no
telemetry, nothing uploaded. The optional OCR model is downloaded once and then
loaded strictly offline.

Supported today (Singapore):

| Bank | Statement | PDF type | Engine used |
|---|---|---|---|
| UOB | Credit card (e.g. UOB One Card) | text layer | text layer |
| UOB | Deposit "Statement of Account" (One Account) | text layer | text layer |
| DBS / POSB | Consolidated statement (deposit accounts) | text layer | text layer |
| HSBC | Credit card | **no text layer** (glyphs drawn as vector paths) | on-device OCR (GLM-OCR on MLX) |

## Why you can trust the numbers

Every statement prints its own totals, and the parser checks them all before it
stores anything:

- **Credit cards:** previous balance + debits − credits must equal the printed
  sub total, the total balance and the amount due (HSBC: purchases & debits,
  payments & credits and total account balance).
- **Deposit accounts:** every row's amount must equal the change in the running
  balance, and the sums must match the printed total withdrawals, total
  deposits and closing balance. The withdrawal/deposit sign comes from the
  balance change, so it never depends on column positions.

A statement that doesn't reconcile is rejected, unless you explicitly allow it.
It is never stored as if it were correct. A misread digit anywhere in an
amount fails a check.

## Use it

```bash
uv sync                                  # core: text-layer statements
uv sync --extra vlm                      # + on-device OCR for image-only PDFs (HSBC)
uv run estatement download-model         # one-time ~2 GB download of GLM-OCR weights
```

The OCR model is pinned to one Hugging Face commit, and every file is checked
against a pinned SHA-256 after download and again before it is loaded.

```bash
uv run estatement import ~/Downloads/*.pdf      # parse, verify, store (dedupes by file hash)
uv run estatement export --out sept.csv --start 2026-09-01 --end 2026-09-30
uv run estatement parse statement.pdf --csv out.csv   # one-off, no database
uv run estatement serve                         # web UI on http://127.0.0.1:8765
uv run --extra app estatement app               # same UI in a native window
```

Database: `~/Library/Application Support/estatement/estatement.sqlite`, created
with owner-only (0600) permissions. Amounts are integer cents. Card and account
numbers keep only the last 4 digits. The PDF itself is never stored, only its
SHA-256 for de-duplication.

Sign convention: negative = money out (card spend, withdrawal), positive =
money in (card payment or refund, deposit). Credit-card balances are amounts
owed.

### macOS app

```bash
uv sync --all-extras
cd packaging && uv run pyinstaller estatement.spec --noconfirm --distpath ../dist --workpath ../build
open ../dist/eStatement.app
```

This produces a self-contained `eStatement.app` (~550 MB, arm64) with the parser,
the UI in a native WebKit window, and the MLX OCR runtime. OCR weights are not
bundled; the app offers to download them the first time an image-only PDF
needs them (or when you pick the OCR engine). From a terminal:
`dist/eStatement.app/Contents/MacOS/eStatement download-model`. The app is
ad-hoc signed. For other Macs, sign it with a Developer ID and notarize it, or
right-click > Open the first time.

The local server binds to `127.0.0.1` on a random port, rejects non-localhost
`Host` headers (DNS rebinding), and requires a per-launch token on every API
call, so other web pages in your browser can't read or write your data.

## How it works

```
PDF ──► extraction backend ──► lines ──► bank parser ──► Statement ──► reconcile checks ──► SQLite / CSV
         textlayer (PyMuPDF)             uob_cc, uob_deposit,
         vlm (GLM-OCR, MLX)              dbs, hsbc_cc
```

- `backends/` turn a PDF into text lines. Every backend produces the same
  shape, so bank parsers don't care where the text came from.
- `banks/` hold per-layout rules. Deposit statements share one running-balance
  engine (`banks/running_balance.py`), so a new deposit layout is mostly a few
  regexes.
- `auto` mode uses the text layer when the PDF has one. Otherwise it OCRs, and
  if the OCR result doesn't reconcile it retries at another render resolution
  (see the eval below for why).

### Adding a bank

1. Drop a statement in `data/statements/` and look at the extracted lines
   (`eval/debug.py` masks digits so you can share output safely).
2. Write `banks/<bank>.py` with `matches(text)` and `parse(lines)`. Use
   `running_balance.Layout` for deposit accounts. Always emit `Check`s against
   the printed totals.
3. Register it in `banks/__init__.py`. Run `uv run python eval/make_ground_truth.py`
   and `uv run pytest`.

## Comparison of extraction approaches

Evaluated on four real statements (178 transactions; UOB card 95, UOB One 52,
DBS 22, HSBC 9). Ground truth for the three text-layer PDFs is the text layer
itself, accepted only because every printed total reconciles. HSBC was
transcribed by hand from the page image. "Row perfect" means date, amount,
description, reference and balance all exact. Reproduce with
`uv run python eval/compare.py`, which prints metrics only.

**Summary** (4 statements, 178 transactions):

| Approach | Statements reconciled | Row recall | Row perfect | Total time |
|---|---|---|---|---|
| **auto: text layer, else GLM-OCR + retry** (shipped default) | **4/4** | **100%** | **100%** | 19 s |
| A. Text layer (PyMuPDF), rules per bank | 3/4 (HSBC has no text) | 94.9% | 94.9% | 0.6 s |
| C1. GLM-OCR 0.9B on MLX, retry until reconciled | 2/4 | 98.9% | 96.1% | 498 s |
| C1. GLM-OCR 0.9B on MLX, single pass @200 dpi | 1/4 | 91.6% | 82.6% | 224 s |
| C2. PaddleOCR-VL-1.6 on MLX (page-level, no layout stage) | 0/4 | 85.4% | 64.0% | 95 s |
| B. Docling (layout + table-structure models) | 0/4 | 46.1% | 46.1% | 29 s |
| D. Apple Vision OCR (built into macOS) | 0/4 | 28.1% | 25.8% | 9 s |
| C4. Gemma-4 E4B 4-bit on MLX (general VLM) | 0/4 | 19.7% | 3.4% | 519 s |
| C3. Gemma-4 E2B 4-bit on MLX (general VLM) | 0/4 | 37.6% | 0.0% | 122 s |

**Per statement**: rows exactly right / statement totals reconcile:

| Approach | UOB card (95) | UOB One (52) | DBS (22) | HSBC card (9, image-only) |
|---|---|---|---|---|
| A. Text layer | 100% ✓ | 100% ✓ | 100% ✓ | n/a (no text layer) |
| C1. GLM-OCR + retry | 99% ✗ | 92% ✓ | 91% ✗ | 100% ✓ |
| C2. PaddleOCR-VL-1.6 | 75% ✗ | 52% ✗ | 73% ✗ | 0% ✗ |
| B. Docling | 86% ✗ | 0% ✗ | 0% ✗ | n/a |
| D. Apple Vision | 42% ✗ | 12% ✗ | 0% ✗ | 0% ✗ |
| C3/C4. Gemma-4 E2B / E4B | 0% / 0% ✗ | 0% / 12% ✗ | 0% / 0% ✗ | 0% / 0% ✗ |

Timings are on an M5 Pro with 64 GB.

### Findings

1. **The text layer wins whenever it exists.** UOB and DBS PDFs carry the
   bank's own characters. Reading them with coordinates plus about 60 lines of
   rules per layout is exact (169/169 rows), takes under half a second, and
   needs no model. No ML approach matched it on these files.
2. **OCR is needed for HSBC.** Its PDF draws every glyph as a vector path, so it
   has no text to extract. GLM-OCR (0.9B, MIT licence, on MLX) is the only
   engine that got it fully right (9/9, all three printed totals reconcile, about
   20 s). It is the fallback, used only when a PDF has no text layer.
3. **OCR output varies, so reconciliation is the safety net.** GLM-OCR dropped the
   amount columns of one UOB One page at 200 dpi but not at 150 or 300 dpi, so
   `auto` retries at other resolutions until the totals reconcile. When it never
   reconciles (GLM missed one DBS row and one UOB-card row), the statement is
   flagged and rejected, not stored. The evaluation also caught two places where
   a statement could "reconcile" without comparing any total, and both are fixed.
   *Limitation:* the checks prove amounts and balances. They can't detect a
   misspelled description or a misread date (amounts unaffected). That's why
   GLM's UOB One result reconciles while 92% of its rows are exact.
4. **Docling** rebuilds tables with its own models. That merges and splits cells
   (Ref No. glued into descriptions, card headers folded into column headers),
   loses rows and is 10–100× slower than reading the text layer directly.
5. **PaddleOCR-VL-1.6** run page-at-a-time emits each cell on its own line, and
   its table prompt misaligns amounts. It is designed to run behind its
   PP-DocLayout stage, which was not tested here.
6. **Gemma-4 E2B/E4B** (general-purpose VLMs) paraphrase, skip rows and mangle
   long reference numbers even with a strict transcription prompt. They are not
   suitable for verbatim financial transcription.
7. **Apple Vision** is the fastest (about 1 s/page) and needs no download, but it
   returns unordered boxes. Rebuilding table rows from them, especially on
   HSBC's two-panel layout, lost rows and garbled digits.
8. **LayoutLM** (Microsoft collection) labels tokens rather than reading them.
   The off-the-shelf doc-QA fine-tune answered 4/5 header fields (statement
   date, amount due) but can't produce transaction rows without fine-tuning on
   labelled pages per layout.
9. **Rust/PyO3 not needed.** Text-layer parsing is under 0.5 s per statement;
   the only slow part is OCR inference, which already runs on Metal through MLX.

## Development

Tooling: [uv](https://docs.astral.sh/uv/) for environments and locking,
[ruff](https://docs.astral.sh/ruff/) for lint and format,
[ty](https://docs.astral.sh/ty/) for type checking, and
[pydantic](https://docs.pydantic.dev/) for the domain models (`models.py`)
and the typed API responses. CI runs all of them on macOS.

```bash
uv sync --all-extras
uv run ruff check . && uv run ruff format --check .
uv run ty check
uv run pytest
```

The tests use synthetic statements and a generated PDF. Regression tests against
your own statements run automatically when `data/ground_truth/` and
`data/statements/` exist (both gitignored).

## Privacy notes

- `data/`, `*.pdf`, `*.sqlite` and `*.csv` are gitignored. Never commit statements.
- Parsing makes no network calls. The only network access is fetching the
  pinned public OCR weights from Hugging Face, either with the `download-model`
  command or when you click "Download OCR model" in the app.
