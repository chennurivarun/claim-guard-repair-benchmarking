const configuredApiBase = import.meta.env.VITE_API_URL as string | undefined
const API_BASE = (configuredApiBase?.trim() || "").replace(/\/+$/, "")

export const PAGE_TYPES = [
  "invoice",
  "engineer_assessment",
  "estimate_or_order",
  "credit_note",
  "vehicle_document",
  "service_history",
  "mot",
  "photo",
  "blank",
  "other",
] as const

export type DocumentPageType = (typeof PAGE_TYPES)[number]

export interface DocumentPageRecord {
  id: string
  document_id: string
  document_filename: string
  page_number: number
  width: number | null
  height: number | null
  page_type: DocumentPageType
  classification_confidence: number | null
  classification_source: "pipeline" | "handler"
  extraction_method: string
  rotation: number
  group_id: string | null
  review_status: string
  reprocess_required: boolean
  correction: {
    corrected_by: string
    corrected_at: string
    reason: string
    changed_fields: string[]
  } | null
  image_url: string
}

export interface DocumentReviewBriefing {
  document_summary: string
  content_found: string[]
  why_manual_review: string
  recommended_action: string
  generated_at: string
  model: string
  prompt_version: string
  fallback: boolean
  redaction_counts?: Record<string, number>
  prompt_injection_flags?: string[]
}

export type IntakeGroup = "historical_claim" | "in_house" | "live"

export interface UploadedDocument {
  intake_group?: IntakeGroup | null
  role?: string
  id: string
  filename: string
  status: string
  page_count: number | null
  invoice_units?: number
  reprocess_required: boolean
  kind?:
    "unknown" | "repair_invoice" | "engineer_assessment" | "supporting_evidence"
  paired?: boolean
  manual_review?: boolean
  manual_review_reason?: string | null
  review_briefing?: DocumentReviewBriefing | null
}

export interface DocumentProcessingResult {
  run_id?: string
  status: string
  metrics?: {
    page_count: number
    invoice_units: number
    extracted_lines: number
    engineer_assessments?: number
    manual_review?: boolean
    manual_review_reason?: string
    llm_failures?: string[]
  }
  document: UploadedDocument
  reprocess_required?: boolean
}

interface ApiErrorPayload {
  detail?: string | { message?: string; code?: string }
}

function apiPath(path: string) {
  return `${API_BASE}${path}`
}

async function responseError(response: Response) {
  let message = `API returned ${response.status}`
  try {
    const payload = (await response.json()) as ApiErrorPayload
    const detail = payload.detail
    if (typeof detail === "string") message = detail
    else if (detail?.message) message = detail.message
  } catch {
    // Keep the status fallback when the upstream response is not JSON.
  }
  return new Error(message)
}

async function requestJson<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 15_000
): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(apiPath(path), {
      ...init,
      signal: controller.signal,
    })
    if (!response.ok) throw await responseError(response)
    return response.json() as Promise<T>
  } finally {
    window.clearTimeout(timeout)
  }
}

export function documentApiErrorMessage(error: unknown) {
  if (error instanceof DOMException && error.name === "AbortError") {
    return "Document processing timed out. The file may still be processing; refresh the page list."
  }
  return error instanceof Error ? error.message : "The document request failed."
}

export function fetchDocumentPages(caseReference: string) {
  return requestJson<DocumentPageRecord[]>(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/pages`
  )
}

export function fetchCaseDocuments(caseReference: string) {
  return requestJson<UploadedDocument[]>(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/documents`
  )
}

export function uploadCurrentDocument(
  file: File,
  caseReference: string,
  intakeGroup?: IntakeGroup,
  pairedDocumentId?: string
) {
  const form = new FormData()
  form.append("file", file)
  form.append("role", "current")
  if (intakeGroup) form.append("intake_group", intakeGroup)
  if (pairedDocumentId) form.append("paired_document_id", pairedDocumentId)
  return requestJson<UploadedDocument>(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/documents`,
    { method: "POST", body: form },
    60_000
  )
}

export function processUploadedDocument(documentId: string, force = false) {
  const query = force ? "?force=true" : ""
  return requestJson<DocumentProcessingResult>(
    `/api/v1/documents/${encodeURIComponent(documentId)}/process${query}`,
    { method: "POST" },
    180_000
  )
}

/** One assessment's pairing verdict, as `_pairing_summary` serialises it
 * (`backend/app/api/router.py`). */
export interface PairingSummaryRow {
  assessment_id: string
  document_id: string
  assessment_number: string | null
  pair_status: string
  pair_confidence: number | null
  pair_reasons: string[]
  paired_invoice_id: string | null
  paired_invoice_number: string | null
}

/** What `POST /claims/{ref}/documents/link-sweep` returns: the case reference
 * plus the `_pairing_summary` block, spread in at the top level. */
export interface CaseLinkSweepResult {
  case_reference: string
  assessments: number
  paired: number
  unpaired: number
  details: PairingSummaryRow[]
}

/** The case-wide link / gap-fill sweep, run **once** after a whole batch of
 * repair invoices and engineer estimates has been handed over -- never per
 * file. A per-file sweep re-pairs the same case N times and, worse, can link
 * an estimate to the only invoice loaded so far while the invoice it belongs
 * to is still queued behind it.
 *
 * This is `POST /claims/{ref}/documents/link-sweep`, which exists to do
 * exactly this and nothing else: it calls `run_case_gap_fill` once for the
 * whole case, summarises the pairing, and commits its own work.
 *
 * It is deliberately **not** `POST /claims/{ref}/compare`. That endpoint, on
 * a case that already carries a comparison, runs `reprocess_case`: a new
 * `ProcessingRun`, every handler mapping-review decision from the previous
 * run discarded, the LLM adjudicator re-run, and `CASE_COMPARISON_COMPLETED`
 * audit events written against `pilot.handler` for an action no handler took.
 * None of that belongs behind an Upload button. */
export function runCaseLinkSweep(caseReference: string) {
  return requestJson<CaseLinkSweepResult>(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/documents/link-sweep`,
    { method: "POST" },
    180_000
  )
}

export function correctDocumentPage(
  pageId: string,
  correction: {
    actor: string
    reason: string
    pageType: DocumentPageType
    groupId: string | null
    rotation: number
  }
) {
  return requestJson<DocumentPageRecord & { changed_fields: string[] }>(
    `/api/v1/pages/${encodeURIComponent(pageId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actor: correction.actor,
        reason: correction.reason,
        page_type: correction.pageType,
        group_id: correction.groupId,
        rotation: correction.rotation,
      }),
    }
  )
}

export function documentImageUrl(path: string) {
  if (/^(https?:|data:|blob:)/.test(path)) return path
  return apiPath(path)
}
