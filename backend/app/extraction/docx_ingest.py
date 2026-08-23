"""Pure-Python DOCX-to-PDF ingestion path used when LibreOffice is unavailable.

The extraction pipeline (see ``app.extraction.pdf_pipeline``) only consumes
PDF input, and its native-text tier expects machine-readable text (at least
80 characters and 20 words per content page). This module reads a ``.docx``
with ``python-docx`` and renders its paragraphs and tables into a plain,
text-based PDF with ``reportlab``. Visual fidelity with the original Word
document is explicitly not a goal -- the only requirement is that the
resulting PDF's embedded text can be extracted faithfully.
"""

from __future__ import annotations

import io

from docx import Document as DocxDocument
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 18 * mm
RIGHT_MARGIN = 18 * mm
TOP_MARGIN = 18 * mm
BOTTOM_MARGIN = 18 * mm
BODY_FONT = "Helvetica"
BODY_FONT_SIZE = 10.5
BODY_LEADING = 14
TABLE_FONT = "Courier"
TABLE_FONT_SIZE = 9.5
TABLE_LEADING = 12.5
USABLE_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN
_MEASURE = canvas.Canvas(io.BytesIO())


def _iter_block_items(document: DocxDocument) -> list[DocxParagraph | DocxTable]:
    """Return the document body's paragraphs and tables in document order."""

    body = document.element.body
    blocks: list[DocxParagraph | DocxTable] = []
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            blocks.append(DocxParagraph(child, document))
        elif child.tag.endswith("}tbl"):
            blocks.append(DocxTable(child, document))
    return blocks


def _table_row_text(table: DocxTable) -> list[str]:
    """Render each table row as one text line, columns separated by 2+ spaces.

    The extraction pipeline's native-table heuristics split columns on runs
    of two or more spaces, so cell text is padded accordingly.
    """

    lines: list[str] = []
    for row in table.rows:
        cells = [" ".join(cell.text.split()) for cell in row.cells]
        if not any(cells):
            continue
        lines.append("   ".join(cells))
    return lines


def _wrap_line(text: str, *, font: str, size: float, max_width: float) -> list[str]:
    if not text:
        return [""]
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if _MEASURE.stringWidth(candidate, font, size) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def docx_to_pdf_bytes(content: bytes) -> bytes:
    """Convert DOCX ``content`` to a plain, machine-readable PDF using reportlab.

    Reads paragraphs and tables in document order via ``python-docx``. Table
    rows are rendered as single text lines with cell values separated by at
    least two spaces so the extraction pipeline's column-splitting heuristics
    can still recover them. Returns the generated PDF bytes.
    """

    document = DocxDocument(io.BytesIO(content))
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    cursor_y = PAGE_HEIGHT - TOP_MARGIN

    def new_page() -> None:
        nonlocal cursor_y
        pdf.showPage()
        cursor_y = PAGE_HEIGHT - TOP_MARGIN

    def ensure_space(leading: float) -> None:
        nonlocal cursor_y
        if cursor_y - leading < BOTTOM_MARGIN:
            new_page()

    def draw_line(
        text: str, *, font: str, size: float, leading: float, bold: bool = False
    ) -> None:
        nonlocal cursor_y
        ensure_space(leading)
        face = f"{font}-Bold" if bold and font == "Helvetica" else font
        pdf.setFont(face, size)
        pdf.drawString(LEFT_MARGIN, cursor_y - size, text)
        cursor_y -= leading

    wrote_any_content = False
    for block in _iter_block_items(document):
        if isinstance(block, DocxParagraph):
            text = block.text.strip()
            if not text:
                cursor_y -= BODY_LEADING * 0.4
                continue
            is_heading = (block.style.name or "").lower().startswith("heading")
            for line in _wrap_line(
                text, font=BODY_FONT, size=BODY_FONT_SIZE, max_width=USABLE_WIDTH
            ):
                draw_line(
                    line,
                    font=BODY_FONT,
                    size=BODY_FONT_SIZE,
                    leading=BODY_LEADING,
                    bold=is_heading,
                )
                wrote_any_content = True
        else:
            for line in _table_row_text(block):
                draw_line(
                    line,
                    font=TABLE_FONT,
                    size=TABLE_FONT_SIZE,
                    leading=TABLE_LEADING,
                )
                wrote_any_content = True
            cursor_y -= TABLE_LEADING * 0.5

    if not wrote_any_content:
        draw_line("(empty document)", font=BODY_FONT, size=BODY_FONT_SIZE, leading=BODY_LEADING)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
