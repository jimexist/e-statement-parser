from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .banks import UnknownBank, parse_lines
from .models import Statement

BACKENDS = ("textlayer", "docling", "vlm", "applevision")
# OCR output is not deterministic across render resolutions (a VLM may skip a
# column at one scale and not another), so retry until the totals reconcile.
VLM_DPIS = (150, 300, 200)

# Called with whichever of backend, attempt, page, page_count changed.
Progress = Callable[..., None]


def extract_lines(pdf: Path, backend: str = "textlayer", **kw):
    if backend == "textlayer":
        from .backends import textlayer as mod
    elif backend == "docling":
        from .backends import docling_backend as mod
    elif backend == "vlm":
        from .backends import vlm as mod
    elif backend == "applevision":
        from .backends import applevision as mod
    else:
        raise ValueError(f"unknown backend {backend!r}; choose from {BACKENDS}")
    return mod.extract_lines(pdf, **kw)


def parse_pdf(pdf: Path, backend: str = "auto", progress: Progress | None = None, **kw) -> Statement:
    """Parse a statement. ``auto`` uses the text layer when the PDF has one and
    falls back to the on-device VLM for scanned / image-only PDFs.

    ``progress`` is told the chosen backend and, for OCR, the attempt and page."""
    pdf = Path(pdf)
    if backend == "auto":
        from .backends.textlayer import has_text_layer

        backend = "textlayer" if has_text_layer(pdf) else "vlm"
    if progress:
        progress(backend=backend)
    if backend == "vlm":
        if progress:
            kw["on_page"] = lambda page, page_count: progress(page=page, page_count=page_count)
        if "dpi" not in kw:
            return _parse_vlm_until_reconciled(pdf, progress, **kw)
    stmt = parse_lines(extract_lines(pdf, backend, **kw))
    stmt.meta["backend"] = backend
    return stmt


def _parse_vlm_until_reconciled(pdf: Path, progress: Progress | None = None, **kw) -> Statement:
    best: Statement | None = None
    last_error: Exception | None = None
    for attempt, dpi in enumerate(VLM_DPIS, start=1):
        if progress:
            progress(attempt=attempt)
        try:
            stmt = parse_lines(extract_lines(pdf, "vlm", dpi=dpi, **kw))
        except UnknownBank as e:
            last_error = e
            continue
        stmt.meta.update(backend="vlm", dpi=str(dpi), attempts=str(attempt))
        if stmt.ok:
            return stmt
        if best is None or sum(c.ok for c in stmt.checks) > sum(c.ok for c in best.checks):
            best = stmt
    if best is None:
        raise last_error or UnknownBank("no parser recognises this statement")
    best.warnings.append(f"OCR totals did not reconcile at any of {VLM_DPIS} dpi")
    return best
