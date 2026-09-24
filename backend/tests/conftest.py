from pathlib import Path

import fitz
import pytest
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


@pytest.fixture
def assessment_cells_pdf():
    """Render fixture table cells separately, as Word/PDF exporters can do.

    No injected column separators: native extraction sees cells on separate
    lines while the visual page still contains aligned table rows.
    """
    def render(format_number: int, *, reverse_draw_order: bool = False) -> bytes:
        source = Path(__file__).resolve().parents[2] / "sample-data" / "client-formats"
        document = Document(source / f"DL_Auda_format_{format_number}_assessment.docx")
        pages: list[list[tuple[float, float, str]]] = [[]]
        y = 30
        for element in document.element.body:
            if element.tag.endswith("}p"):
                rows = [[Paragraph(element, document).text]]
            elif element.tag.endswith("}tbl"):
                rows = [[cell.text.replace("\n", " ") for cell in row.cells]
                        for row in Table(element, document).rows]
            else:
                continue
            widths = [max([fitz.get_text_length(row[i], fontsize=9)
                           for row in rows if len(row) > i] + [0]) + 30
                      for i in range(max(map(len, rows)))]
            for row in rows:
                if y > 950:
                    pages.append([])
                    y = 30
                x = 30
                for index, cell in enumerate(row):
                    if cell.strip():
                        pages[-1].append((x, y, cell))
                    x += widths[index]
                y += 17
        with fitz.open() as pdf:
            for cells in pages:
                page = pdf.new_page(width=1800, height=1000)
                for x, y, text in reversed(cells) if reverse_draw_order else cells:
                    page.insert_text((x, y), text, fontsize=9)
            return pdf.tobytes()
    return render
