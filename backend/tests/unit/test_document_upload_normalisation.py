import io

import fitz
import pytest
from docx import Document as DocxDocument
from PIL import Image

import app.services.document_processing as document_processing


def _build_invoice_docx() -> bytes:
    """Build a small in-memory .docx resembling a repair invoice."""

    document = DocxDocument()
    document.add_heading("INVOICE 12345", level=1)
    document.add_paragraph("Supplier: Acme Bodyshop Ltd")
    document.add_paragraph("Customer: Jane Doe")

    table = document.add_table(rows=1, cols=3)
    header = table.rows[0].cells
    header[0].text = "Description"
    header[1].text = "Qty"
    header[2].text = "Price"
    line_items = [
        ("Front bumper replacement", "1", "250.00"),
        ("Headlamp assembly, offside", "1", "180.00"),
        ("Paint and refinish - bumper", "2", "95.00"),
    ]
    for description, qty, price in line_items:
        row = table.add_row().cells
        row[0].text = description
        row[1].text = qty
        row[2].text = price

    document.add_paragraph("Subtotal: 620.00")
    document.add_paragraph("VAT: 124.00")
    document.add_paragraph("Total: 744.00")

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_docx_uses_deterministic_table_preserving_conversion(monkeypatch) -> None:
    monkeypatch.setattr(document_processing.shutil, "which", lambda _: "/usr/bin/soffice")
    def unexpected_conversion(*args, **kwargs):
        pytest.fail("A text/table DOCX must not depend on the installed office renderer")
    monkeypatch.setattr(document_processing, "_convert_with_libreoffice", unexpected_conversion)
    docx_bytes = _build_invoice_docx()
    normalised = document_processing.normalise_document_upload(
        "repair.docx", docx_bytes
    )

    assert normalised.content.startswith(b"%PDF-")
    assert normalised.stored_filename == "repair.pdf"
    assert normalised.source_format == "docx-python"


def test_docx_header_evidence_uses_office_conversion(monkeypatch) -> None:
    document = DocxDocument(io.BytesIO(_build_invoice_docx()))
    document.sections[0].header.paragraphs[0].text = "Invoice number: HEADER-99"
    image = io.BytesIO()
    Image.new("RGB", (12, 12), "white").save(image, format="PNG")
    document.sections[0].header.paragraphs[0].add_run().add_picture(io.BytesIO(image.getvalue()))
    content = io.BytesIO()
    document.save(content)
    monkeypatch.setattr(document_processing.shutil, "which", lambda _: "/usr/bin/soffice")
    expected_pdf = b"%PDF-1.7\nconverted with header"
    monkeypatch.setattr(document_processing, "_convert_with_libreoffice", lambda *args: expected_pdf)
    result = document_processing.normalise_document_upload("header.docx", content.getvalue())
    assert result.source_format == "docx-libreoffice"
    assert result.content == expected_pdf


def test_docx_unsupported_content_is_not_silently_dropped_without_office(monkeypatch) -> None:
    document = DocxDocument(io.BytesIO(_build_invoice_docx()))
    document.sections[0].footer.paragraphs[0].text = "Total: 744.00"
    image = io.BytesIO()
    Image.new("RGB", (12, 12), "white").save(image, format="PNG")
    document.sections[0].footer.paragraphs[0].add_run().add_picture(io.BytesIO(image.getvalue()))
    content = io.BytesIO()
    document.save(content)
    monkeypatch.setattr(document_processing, "find_libreoffice", lambda: None)
    with pytest.raises(ValueError, match="header or footer"):
        document_processing.normalise_document_upload("footer.docx", content.getvalue())


def test_windows_office_install_is_found_when_not_on_path(tmp_path, monkeypatch):
    program_files = tmp_path / "Program Files"
    executable = program_files / "LibreOffice" / "program" / "soffice.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.setattr(document_processing.shutil, "which", lambda _: None)

    def convert(path, suffix, content):
        assert path == str(executable)
        assert suffix == ".doc"
        return b"%PDF-1.7\nconverted"

    monkeypatch.setattr(document_processing, "_convert_with_libreoffice", convert)
    result = document_processing.normalise_document_upload(
        "assessment.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1synthetic"
    )
    assert result.content == b"%PDF-1.7\nconverted"


def test_docx_falls_back_to_python_pdf_without_libreoffice(monkeypatch) -> None:
    monkeypatch.setattr(document_processing.shutil, "which", lambda _: None)

    docx_bytes = _build_invoice_docx()
    normalised = document_processing.normalise_document_upload("invoice-12345.docx", docx_bytes)

    assert normalised.content.startswith(b"%PDF-")
    assert normalised.stored_filename == "invoice-12345.pdf"
    assert normalised.source_format == "docx-python"

    extracted = fitz.open(stream=normalised.content, filetype="pdf")
    try:
        text = "\n".join(page.get_text() for page in extracted)
    finally:
        extracted.close()

    assert "INVOICE 12345" in text
    assert "Front bumper replacement" in text


def test_doc_without_libreoffice_raises_clear_error(monkeypatch) -> None:
    monkeypatch.setattr(document_processing, "find_libreoffice", lambda: None)

    with pytest.raises(ValueError, match="DOC \\(legacy\\)"):
        document_processing.normalise_document_upload(
            "repair.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1fake-legacy-doc"
        )


def test_pdf_upload_is_not_rewritten() -> None:
    content = b"%PDF-1.7\nexample"
    normalised = document_processing.normalise_document_upload("repair.pdf", content)
    assert normalised.content == content
    assert normalised.stored_filename == "repair.pdf"
    assert normalised.source_format == "pdf"
