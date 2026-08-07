"""Backfill field-level invoice provenance without replacing reviewed records."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.extraction.pdf_pipeline import PDFPipeline, PipelineConfig
from app.models import Document, Invoice


def main() -> None:
    settings = get_settings()
    updated_documents = 0
    updated_lines = 0
    with SessionLocal() as session:
        documents = session.scalars(select(Document).order_by(Document.created_at)).all()
        for document in documents:
            source_path = Path(document.storage_path)
            if not source_path.exists() or not document.invoices:
                continue
            output_dir = (
                Path(settings.storage_dir)
                / "cases"
                / document.case_id
                / document.sha256[:12]
                / "pages"
            )
            analysis = PDFPipeline(PipelineConfig(max_pages=settings.max_pdf_pages)).analyse(
                source_path, output_dir
            )
            pages = {page.page_number: page for page in document.pages}
            for analysed_page in analysis.pages:
                stored_page = pages.get(analysed_page.page_number)
                if stored_page:
                    stored_page.width = analysed_page.width
                    stored_page.height = analysed_page.height
                    stored_page.rendered_image_path = str(analysed_page.rendered_image_path)

            stored_invoices = {invoice.invoice_number: invoice for invoice in document.invoices}
            for extracted in analysis.invoices:
                invoice: Invoice | None = stored_invoices.get(extracted.header.invoice_number)
                if invoice is None:
                    continue
                invoice.extraction_payload_json = extracted.model_dump(mode="json")
                lines = {line.sequence_no: line for line in invoice.line_items}
                for extracted_line in extracted.line_items:
                    line = lines.get(extracted_line.sequence_no)
                    if line is None:
                        continue
                    source = extracted_line.source
                    page = pages.get(source.page_number)
                    line.source_page_id = page.id if page else line.source_page_id
                    line.source_bbox_json = (
                        [source.bbox.x0, source.bbox.y0, source.bbox.x1, source.bbox.y1]
                        if source.bbox
                        else None
                    )
                    line.source_regions_json = {
                        name: [region.x0, region.y0, region.x1, region.y1]
                        for name, region in source.regions.items()
                    } or None
                    line.source_raw_text = source.raw_text
                    updated_lines += 1
            updated_documents += 1
        session.commit()
    print(f"Backfilled provenance for {updated_lines} lines across {updated_documents} documents.")


if __name__ == "__main__":
    main()
