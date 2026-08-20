from pathlib import Path
from types import SimpleNamespace

import fitz

import app.services.document_processing as document_processing


def test_docx_is_converted_to_pdf_before_storage(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(document_processing.shutil, "which", lambda _: "/usr/bin/soffice")

    def fake_run(command, **kwargs):
        output_dir = Path(command[command.index("--outdir") + 1])
        document = fitz.open()
        document.new_page().insert_text((72, 72), "Invoice INV-1")
        document.save(output_dir / "source.pdf")
        document.close()
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(document_processing.subprocess, "run", fake_run)

    normalised = document_processing.normalise_document_upload(
        "repair.docx", b"PK\x03\x04fake-office-package"
    )

    assert normalised.content.startswith(b"%PDF-")
    assert normalised.stored_filename == "repair.pdf"
    assert normalised.source_format == "docx"


def test_pdf_upload_is_not_rewritten() -> None:
    content = b"%PDF-1.7\nexample"
    normalised = document_processing.normalise_document_upload("repair.pdf", content)
    assert normalised.content == content
    assert normalised.stored_filename == "repair.pdf"
    assert normalised.source_format == "pdf"
