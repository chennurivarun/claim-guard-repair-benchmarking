const configuredApiBase = import.meta.env.VITE_API_URL as string | undefined
const API_BASE = (configuredApiBase?.trim() || "").replace(/\/+$/, "")

export const DEFAULT_CASE_REFERENCE = "CG-2026-0048"

export const PAGE_TYPES = [
  "invoice",
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

export interface UploadedDocument {
  id: string
  filename: string
  status: string
  page_count: number | null
  reprocess_required: boolean
}

export interface DocumentProcessingResult {
  run_id?: string
  status: string
  metrics?: {
    page_count: number
    invoice_units: number
    extracted_lines: number
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

export function fetchDocumentPages(caseReference = DEFAULT_CASE_REFERENCE) {
  return requestJson<DocumentPageRecord[]>(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/pages`
  )
}

export function uploadCurrentDocument(
  file: File,
  caseReference = DEFAULT_CASE_REFERENCE
) {
  const form = new FormData()
  form.append("file", file)
  form.append("role", "current")
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
