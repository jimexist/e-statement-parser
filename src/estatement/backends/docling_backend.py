"""Backend B: Docling (IBM) layout + table-structure models, run locally.

Uses the PDF text layer for characters but reconstructs reading order and
tables with its own models, then exports markdown which we flatten to lines.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..models import Line
from .markdown import to_lines

NAME = "docling"


@lru_cache(maxsize=1)
def _converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def extract_lines(pdf: Path) -> list[Line]:
    doc = _converter().convert(str(pdf)).document
    lines: list[Line] = []
    for pno in sorted(doc.pages):
        lines += to_lines(doc.export_to_markdown(page_no=pno), page=pno)
    return lines
