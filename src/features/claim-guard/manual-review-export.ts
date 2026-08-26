import type { ClaimInvoiceSummary } from "@/lib/api"

import type {
  DocumentPageRecord,
  UploadedDocument,
} from "./document-api"

const columns = [
  "document_id",
  "document_name",
  "document_type",
  "processing_status",
  "manual_review_reason",
  "ai_summary",
  "ai_content_found",
  "ai_why_manual_review",
  "ai_recommended_action",
  "ai_model",
  "ai_fallback_used",
  "page_count",
  "page_numbers",
  "invoice_number",
  "invoice_date",
  "repairer",
  "vehicle_registration",
  "vehicle_make",
  "vehicle_model",
  "extracted_line_count",
  "extracted_lines",
] as const

function csvCell(value: unknown) {
  const text = value == null ? "" : String(value)
  return `"${text.replaceAll('"', '""')}"`
}

export function buildManualReviewCsv(
  documents: UploadedDocument[],
  pages: DocumentPageRecord[],
  invoices: ClaimInvoiceSummary[]
) {
  const invoiceByDocumentId = new Map(
    invoices
      .filter((invoice) => invoice.document_id)
      .map((invoice) => [invoice.document_id as string, invoice])
  )
  const reviewDocuments = documents.filter(
    (document) => document.manual_review || document.status === "failed"
  )
  const rows = reviewDocuments.map((document) => {
    const briefing = document.review_briefing
    const invoice = invoiceByDocumentId.get(document.id)
    const pageNumbers = pages
      .filter((page) => page.document_id === document.id)
      .map((page) => page.page_number)
      .sort((left, right) => left - right)
    const values: Record<(typeof columns)[number], unknown> = {
      document_id: document.id,
      document_name: document.filename,
      document_type: document.kind ?? "unknown",
      processing_status: document.status,
      manual_review_reason: document.manual_review_reason,
      ai_summary: briefing?.document_summary,
      ai_content_found: briefing?.content_found.join(" | "),
      ai_why_manual_review: briefing?.why_manual_review,
      ai_recommended_action: briefing?.recommended_action,
      ai_model: briefing?.model,
      ai_fallback_used: briefing?.fallback ?? "",
      page_count: document.page_count ?? pageNumbers.length,
      page_numbers: pageNumbers.join(" | "),
      invoice_number: invoice?.invoice_number,
      invoice_date: invoice?.invoice_date,
      repairer: invoice?.supplier_name,
      vehicle_registration: invoice?.vehicle?.registration,
      vehicle_make: invoice?.vehicle?.make,
      vehicle_model: invoice?.vehicle?.model,
      extracted_line_count: invoice?.lines.length ?? 0,
      extracted_lines: invoice ? JSON.stringify(invoice.lines) : "",
    }
    return columns.map((column) => csvCell(values[column])).join(",")
  })
  return [columns.map(csvCell).join(","), ...rows].join("\r\n")
}

export function downloadManualReviewCsv(
  caseReference: string,
  documents: UploadedDocument[],
  pages: DocumentPageRecord[],
  invoices: ClaimInvoiceSummary[]
) {
  const blob = new Blob([buildManualReviewCsv(documents, pages, invoices)], {
    type: "text/csv;charset=utf-8",
  })
  const url = URL.createObjectURL(blob)
  const anchor = window.document.createElement("a")
  anchor.href = url
  anchor.download = `${caseReference}-manual-review-staging.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}
