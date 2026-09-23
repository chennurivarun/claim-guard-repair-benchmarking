"""Check the real upload conversion on local files without uploading or extracting them.

Run from backend: uv run python scripts/diagnose_intake.py --folder "C:\\path\\to\\documents"
Prints filenames and conversion results, never document text or API keys.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.llm.factory import llm_configuration_status  # noqa: E402
from app.services.document_processing import (  # noqa: E402
    find_libreoffice,
    normalise_document_upload,
)


def check_file(path: Path) -> tuple[bool, str]:
    """Exercise exactly the converter used before a document record is created."""
    try:
        normalised = normalise_document_upload(path.name, path.read_bytes())
        with fitz.open(stream=normalised.content, filetype="pdf") as pdf:
            if pdf.needs_pass:
                return False, "Encrypted PDF: cannot be extracted by this application."
            if len(pdf) > get_settings().max_pdf_pages:
                return False, f"PDF exceeds the {get_settings().max_pdf_pages}-page limit."
            sparse_pages = sum(
                len(page.get_text().strip()) < 80 or len(page.get_text("words")) < 20
                for page in pdf
            )
            return True, (
                f"{normalised.source_format}; {len(pdf)} pages; "
                f"{sparse_pages} pages need OCR/image reading"
            )
    except ValueError as exc:
        return False, str(exc)
    except Exception as exc:
        # Avoid printing raw exception payloads that could contain document data.
        return False, f"Cannot read or convert file ({type(exc).__name__})."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True, type=Path)
    args = parser.parse_args()
    if not args.folder.is_dir():
        parser.error("--folder must be an existing local folder")

    config = get_settings()
    print("Upload conversion diagnostic — no AI calls, uploads or database changes")
    print(f"Text model: {config.llm_model}; configuration: {llm_configuration_status(config)}")
    print(f"Text extraction enabled: {config.llm_text_extraction_enabled}")
    print(f"Vision enabled: {config.llm_vision_enabled}")
    if config.llm_vision_enabled:
        print(f"Vision model: {config.llm_vision_model or config.llm_model}")
    print(f"OCR provider: {config.document_ocr_provider}")
    print(f"LibreOffice found: {'yes' if find_libreoffice() else 'NO'}")
    print("These settings are not a live AI or OCR connectivity test.\n")

    supported = {".pdf", ".doc", ".docx"}
    files = sorted(path for path in args.folder.rglob("*") if path.is_file())
    rejected = Counter(path.suffix.lower() or "[no extension]" for path in files
                       if path.suffix.lower() not in supported)
    checked = [path for path in files if path.suffix.lower() in supported]
    failures = 0
    for path in checked:
        ok, detail = check_file(path)
        failures += not ok
        name = str(path.relative_to(args.folder)).replace("\n", " ").replace("\r", " ")
        print(f"{'PASS' if ok else 'FAIL'} | {name} | {detail}")
    if rejected:
        print("Ignored by the application's file picker: " + ", ".join(
            f"{count} {extension}" for extension, count in sorted(rejected.items())
        ))
    print(f"\n{len(checked)} supported files checked; {failures} failed; {len(files) - len(checked)} ignored.")
    print("PASS means conversion succeeded, not that extraction or pairing succeeded.")
    print("A FAIL here occurs before AI. Keep the originals locally; share this output to diagnose it.")
    return 1 if failures or not checked else 0


if __name__ == "__main__":
    raise SystemExit(main())
