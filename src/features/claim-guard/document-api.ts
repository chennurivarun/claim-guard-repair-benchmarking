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
  original_url?: string | null
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
  original_url?: string | null
  status: string
  page_count: number | null
  invoice_units?: number
  extracted_invoice_units?: number
  assessment_units?: number
  assessment_operation_count?: number | null
  can_retry_assessment_details?: boolean
  processing_error?: string | null
  can_retry_extraction?: boolean
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

/** Exported for `benchmark-api.ts`, whose endpoints share this module's
 * timeout and error handling. */
export async function requestJson<T>(
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
  pairedDocumentId?: string,
  documentKind?: "engineer_assessment"
) {
  const form = new FormData()
  form.append("file", file)
  form.append("role", "current")
  if (intakeGroup) form.append("intake_group", intakeGroup)
  if (documentKind) form.append("document_kind", documentKind)
  if (pairedDocumentId) form.append("paired_document_id", pairedDocumentId)
  return requestJson<UploadedDocument>(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/documents`,
    { method: "POST", body: form },
    // Allow upload time in addition to the backend's 60-second Word conversion limit.
    90_000
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

export function retryEmptyDocument(documentId: string) {
  return requestJson<DocumentProcessingResult>(
    `/api/v1/documents/${encodeURIComponent(documentId)}/process?retry_empty=true`,
    { method: "POST" },
    180_000
  )
}

export function retryAssessmentDetails(documentId: string) {
  return requestJson<{ document: UploadedDocument; operation_count: number; status: string }>(
    `/api/v1/documents/${encodeURIComponent(documentId)}/assessment-details`,
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

/** One pairing key's verdict, as the backend serialises it. Re-declared here
 * rather than imported from `@/lib/api` so the mapping screen and its API
 * stay in one module; the two shapes are the same `_KeyVerdict.as_payload`. */
export interface MappingKeyVerdict {
  key: string
  label: string
  state: "matched" | "conflict" | "not_compared" | "placeholder"
  compared: boolean
  absent_on: "invoice" | "assessment" | "both" | null
  placeholder_on: "invoice" | "assessment" | "both" | null
  assessment_value: string | null
  invoice_value: string | null
  text: string
}

/** How the link on the row came about. `"manual"` means a handler chose it on
 * the mapping screen; everything else came from the printed-identity rule. */
export type PairSource = "automatic" | "manual"

/** The handler's standing instruction about one assessment's invoice.
 * `applied` is false when the instruction could not be carried out -- the
 * chosen invoice has left the claim, or another handler link holds it. */
export interface MappingOverride {
  state: "linked" | "cleared"
  invoice_id: string | null
  invoice_number: string | null
  actor: string | null
  at: string | null
  reason: string | null
  applied: boolean
}

export interface MappingInvoiceOption {
  invoice_id: string
  document_id: string
  document_filename: string | null
  invoice_number: string | null
  supplier_name: string | null
  registration: string | null
  claim_reference: string | null
  policy_number: string | null
  intake_group: IntakeGroup | null
  manual_review?: boolean
  manual_review_reason?: string | null
  unmapped_assessment?: boolean
}

export interface MappingAssessmentRow {
  assessment_id: string
  document_id: string
  document_filename: string | null
  assessment_number: string | null
  registration: string | null
  claim_reference: string | null
  policy_number: string | null
  vehicle_make: string | null
  vehicle_model: string | null
  intake_group: IntakeGroup | null
  pair_status: string
  pair_source: PairSource
  pair_confidence: number | null
  pair_reasons: string[]
  pair_key_verdicts: MappingKeyVerdict[]
  paired_invoice_id: string | null
  paired_invoice_number: string | null
  manual_override: MappingOverride | null
}

export interface MappingApproval {
  approved: boolean
  approved_by: string | null
  approved_at: string | null
  approved_pairs: Record<string, string | null>
}

/** `GET /claims/{ref}/document-mapping`. */
export interface CaseMappingPayload {
  case_reference: string
  approval: MappingApproval
  invoices: MappingInvoiceOption[]
  assessments: MappingAssessmentRow[]
  assessments_total: number
  paired: number
  unpaired: number
  manual: number
}

/** What a handler may do to one assessment's pairing.
 *
 * `reset` is not `unlink`. `unlink` is an instruction -- "this assessment
 * pairs with nothing" -- which the automatic rule must not overturn on the
 * next upload. `reset` withdraws the instruction and hands the decision back
 * to the rule. */
export type MappingOverrideDecision = "link" | "unlink" | "reset"

/** With `intakeGroup`, the mapping of one source only (third party is
 * `historical_claim`, In-house is `in_house`, the new invoice is `live`).
 * Without it, the whole claim, as before. */
export function fetchCaseMapping(
  caseReference: string,
  intakeGroup?: IntakeGroup
) {
  const query = intakeGroup
    ? `?${new URLSearchParams({ intake_group: intakeGroup }).toString()}`
    : ""
  return requestJson<CaseMappingPayload>(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/document-mapping${query}`
  )
}

export function overrideAssessmentMapping(
  caseReference: string,
  assessmentId: string,
  input: {
    actor: string
    decision: MappingOverrideDecision
    invoiceId?: string | null
    reason?: string | null
  }
) {
  return requestJson<CaseMappingPayload>(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/document-mapping/assessments/${encodeURIComponent(assessmentId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actor: input.actor,
        decision: input.decision,
        // The server refuses an invoice on anything but a link, so it is
        // only ever sent with one.
        ...(input.decision === "link" ? { invoice_id: input.invoiceId } : {}),
        reason: input.reason ?? null,
      }),
    },
    60_000
  )
}

/** Approve the mapping. This is what runs the case-wide link / gap-fill sweep
 * now: the handler has just said the pairs are right, so the fill runs
 * against the pairs they confirmed rather than on a standing button.
 *
 * Approval is recorded per intake group: approving third party does not
 * approve In-house. The group is only sent when there is one, so the
 * whole-claim screen under Advanced tools posts exactly what it did before. */
export function approveCaseMapping(
  caseReference: string,
  actor: string,
  intakeGroup?: IntakeGroup
) {
  return requestJson<CaseMappingPayload>(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/document-mapping/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        intakeGroup ? { actor, intake_group: intakeGroup } : { actor }
      ),
    },
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
