import type {
  ClaimWorkspace,
  LiabilityStatus,
  WorkspaceBootstrap,
} from "@/features/claim-guard/types"

const configuredApiBase = import.meta.env.VITE_API_URL as string | undefined
const API_BASE = (configuredApiBase?.trim() || "").replace(/\/+$/, "")

export type ReportFormat = "json" | "xlsx" | "sqlite" | "docx" | "pdf"

export interface BenchmarkStatisticsPayload {
  min: number | null
  max: number | null
  mean: number | null
  median: number | null
  mode: number | null
  p25: number | null
  p75: number | null
  p90?: number | null
  outlierCount: number
  count: number
}

export interface BenchmarkObservationPayload {
  id: string
  invoiceDate: string | null
  amount: number | null
  vehicleClass: string
  vehicleMake: string | null
  vehicleModel: string | null
  rawDescription: string | null
  sourceRecordId: string | null
  repairer: string
  sourceGroup?: "in_house" | "historical_claim" | string
  source: Record<string, unknown>
}

export interface BenchmarkExceptionPayload {
  observationId: string
  invoiceNumber: string
  repairer: string
  description: string | null
  amount: number
  p90: number
  difference: number
  percentageAboveP90: number
  historicalCount: number
}

export interface BenchmarkDashboardPayload {
  summary: {
    averageRepairCost: number | null
    averageLabourRate: number | null
    mostObservedItem: string | null
    observationCount: number
    mostExpensiveRepairCategory: string | null
    mostExpensiveRepairAverage: number | null
  }
  vehicleCategories: Array<{
    vehicleClass: string
    averageCost: number | null
    count: number
  }>
  benchmarks: Array<{
    ontologyItemId: string
    item: string
    vehicleClass: string
    vehicleMake?: string | null
    vehicleModel?: string | null
    statistics: BenchmarkStatisticsPayload
    labourStatistics: BenchmarkStatisticsPayload
    sourceCount: number
    invoiceCount: number
    exceptionCount: number
    exceptionInvoiceCount: number
    exceptions: BenchmarkExceptionPayload[]
    sourceObservations?: BenchmarkObservationPayload[]
    sampleStrength: "insufficient" | "usable" | "strong"
    latestObservedAt: string | null
  }>
  repairerTrends: Array<{
    repairer: string
    challengeCount: number
    invoiceCount: number
    itemCount: number
    totalDifference: number
    maximumDifference: number
    items: Array<{
      ontologyItemId: string
      item: string
      challengeCount: number
      invoiceCount: number
      totalDifference: number
      maximumDifference: number
      maximumPercentageAboveP90: number
      exceptions: BenchmarkExceptionPayload[]
    }>
  }>
  filterOptions: {
    vehicleClasses: string[]
    repairItems: Array<{ id: string; name: string }>
  }
  appliedFilters: {
    vehicleClass: string | null
    ontologyItemId: string | null
    dateFrom: string | null
    dateTo: string | null
    minimumCount: number
    challengeThresholdPct: number
    minimumChallengeAmount: number
  }
  dataQuality: {
    invoiceObservationCount: number
    validCostCount: number
    invalidOrMissingCostCount: number
    classifiedCount: number
    unclassifiedCount: number
    classifiedCoveragePct: number
    latestObservationDate: string | null
  }
  definitions: {
    cost: string
    labour: string
    challengeGate: string
    coverageNote: string
    officialClasses: Record<string, string>
  }
}

export interface HistoricalObservationPayload {
  id: string
  claim_reference: string | null
  source_record_id: string | null
  invoice_date: string | null
  description: string | null
  line_total_net: number | null
  approved_amount_net: number | null
  settled_amount_net: number | null
  vehicle: {
    make: string | null
    model: string | null
    variant: string | null
    year: number | null
    class: string | null
  }
  source: Record<string, unknown>
}

export interface LinePriceEvidenceObservation {
  id: string
  sourceRecordId: string | null
  sourceGroup: "in_house" | "historical_claim"
  origin:
    "synthetic_in_house" | "historical_claim_store" | "uploaded_invoice_batch"
  claimReference?: string | null
  invoiceId?: string | null
  invoiceNumber?: string | null
  invoiceDate: string | null
  repairer?: string | null
  description: string | null
  amountNet: number
  vehicle: {
    make?: string | null
    model?: string | null
    variant?: string | null
    year?: number | null
  }
  sourceReference?: string | null
  included: boolean
  inclusionReason: string
}

export interface LinePriceEvidenceSource {
  available: boolean
  eligible: boolean
  valueNet: number | null
  configuredWeight: number
  effectiveWeight: number
  method: string | null
  scope: string
  sampleCount: number
  currentInvoiceExcluded: boolean
  synthetic?: boolean
  observations: LinePriceEvidenceObservation[]
}

export interface LineExternalPriceEvidenceSource {
  price_net: number
  unit_price_net?: number
  quantity?: number
  source_reference: string | null
  source_title: string | null
  vehicle_make: string | null
  vehicle_model: string | null
  approval_status?: string | null
  eligible: boolean
  eligibility_reason?: string | null
}

export interface LinePriceEvidencePayload {
  caseReference: string
  invoiceId: string
  lineId: string
  description: string
  ontologyItem: { id: string; code: string; name: string } | null
  sources: {
    inHouse: LinePriceEvidenceSource
    historicalClaims: LinePriceEvidenceSource
    externalReference: {
      available: boolean
      eligible: boolean
      valueNet: number | null
      configuredWeight: number
      effectiveWeight: number
      method: string | null
      sources: LineExternalPriceEvidenceSource[]
    }
  }
  decision: {
    billedNet: number
    supportedNet: number | null
    challengeNet: number
    thresholdPct: number
    minimumDifferenceNet: number
    comparisonStatus: string | null
    rationale: string | null
  }
  calculation: Array<{
    step: number
    label: string
    value?: string | number | null
    detail?: string | null
    passed?: boolean | null
  }>
}

export interface DataReadinessPayload {
  ready: boolean
  ontology_items: number
  historical_claims: number
  issues: string[]
}

export interface ClaimInvoiceSummary {
  intake_group?: "historical_claim" | "in_house" | "live" | null
  id: string
  invoice_number: string | null
  invoice_date: string | null
  uploaded_at?: string | null
  document_id?: string
  document_filename: string
  supplier_name: string | null
  vehicle?: {
    registration: string | null
    vin: string | null
    make: string | null
    model: string | null
    mileage: number | null
  } | null
  totals: {
    gross: number | null
  }
  challenge_review: {
    positive: number
    approved: number
    rejected: number
    unresolved: number
  }
  challenge_lines?: Array<{
    id: string | null
    line_id: string | null
    description: string | null
    billed_net: number
    supported_net: number
    in_house_p90_net: number | null
    historical_claims_p90_net: number | null
    external_price_net: number | null
    external_price_sources?: Array<{
      price_net: number
      source_reference: string
      source_title: string | null
      vehicle_make: string
      vehicle_model: string
    }>
    external_price_method?: string | null
    challenge_net: number
    status: string
    benchmark_source: string | null
  }>
  lines: unknown[]
}

export interface EngineerAssessmentVariancePayload {
  invoice_id: string
  invoice_line_item_id: string
  engineer_amount: number | string | null
  invoice_amount: number | string | null
  difference_amount: number | string | null
  difference_percentage: number | string | null
  threshold_status: "within_threshold" | "above_5_percent" | "above_10_percent"
  explanation: string
}

export interface EngineerAssessmentPayload {
  field_sources?: Record<
    string,
    { document_id: string; label: string; value: string | number }
  >
  vehicle_make?: string | null
  vehicle_model?: string | null
  vin?: string | null
  mileage?: number | null
  id: string
  document_id: string
  assessment_number: string | null
  claim_reference: string | null
  registration: string | null
  pair_status: "paired" | "unpaired"
  pair_confidence: number | null
  pair_reasons: string[]
  paired_invoice_id: string | null
  totals: Record<string, number | string | null>
  operations: Array<{
    id: string
    category: string
    code: string | null
    description: string
    total_net: number | string | null
    source_page_id: string | null
    variances: EngineerAssessmentVariancePayload[]
  }>
}

export interface InvoiceExtractLine {
  id: string
  sequence_no: number
  line_item_type: string | null
  raw_category: string | null
  description: string
  quantity: string | number | null
  unit_price: string | number | null
  line_total: string | number | null
  is_section_total: boolean
  item_kind: string
}

export interface InvoiceExtractPayload {
  invoice_id: string
  invoice_number: string | null
  vehicle_make: string | null
  vehicle_model: string | null
  vehicle_registration: string | null
  claim_number: string | null
  policy_number: string | null
  field_sources: Record<
    string,
    { document_id: string; label: string; value: string | number }
  >
  lines: InvoiceExtractLine[]
}

export interface AssessmentExtractLine {
  sequence_no: number
  line_item_type: string | null
  raw_category: string | null
  description: string
  work_units: string | number | null
  hours: string | number | null
  unit_price: string | number | null
  line_total: string | number | null
  price_derived: boolean | null
}

export interface AssessmentExtractPayload {
  assessment_id: string
  assessment_number: string | null
  vehicle_make: string | null
  vehicle_model: string | null
  vehicle_registration: string | null
  claim_number: string | null
  policy_number: string | null
  paired_invoice_number: string | null
  pair_status: "paired" | "unpaired"
  pair_confidence: number | null
  pair_reasons: string[]
  /** Optional: per-field pairing verdicts, if the pairing engine emits them. */
  pair_key_verdicts?: string[]
  lines: AssessmentExtractLine[]
}

export interface SectionBreakdownRow {
  id: string
  category: string
  raw_category: string | null
  description: string
  work_units: string | number | null
  hours: string | number | null
  unit_price_net: string | number | null
  total_net: string | number | null
}

export interface SectionBreakdownPayload {
  invoice_id: string
  invoice_number: string | null
  invoice_line_item_id: string
  line_item_type: string
  raw_category: string | null
  description: string
  invoice_total: string | number | null
  assessment_id: string | null
  assessment_total: string | number | null
  matches: boolean | null
  difference: string | null
  breakdown_source: string
  rows: SectionBreakdownRow[]
  /** Optional: false means the assessment has no rows for this section at all
   * (distinct from an empty `rows` array meaning "not captured yet"). */
  breakdown_available?: boolean
  /** Optional: the assessment's own printed rows total, shown beside the
   * section total when the client format prints one. */
  rows_total?: string | number | null
}

export interface ClaimExtractsPayload {
  invoice_extracts: InvoiceExtractPayload[]
  assessment_extracts: AssessmentExtractPayload[]
  section_breakdowns: SectionBreakdownPayload[]
}

export interface LineCorrectionInput {
  actor: string
  reason: string
  description: string
  quantity: number
  unitPriceNet: number
  lineTotalNet: number
}

export type ExtractionDecision = "approved" | "rejected" | "undo"

export interface ExtractionDecisionInput {
  decision: ExtractionDecision
  actor: string
  reason?: string
}

export interface SettlementInput {
  agreedAmountNet: number
  agreedAt: string
  recordedBy: string
  note?: string
  lines: Array<{ lineItemId: string; agreedAmountNet: number }>
}

export type MappingDecisionAction = "approve" | "change" | "reject" | "bundle"

export interface MappingBundleComponentInput {
  ontologyItemId: string
  allocatedNet?: number
  quantity?: number
  unit?: string
}

export interface MappingDecisionInput {
  actor: string
  decision: MappingDecisionAction
  rationale: string
  ontologyItemId?: string
  bundleComponents?: MappingBundleComponentInput[]
}

export interface ManualResearchInput {
  requestedBy: string
  queryText: string
  sourceAllowListVersion: string
  suggestion: {
    canonicalName: string
    itemType: string
    category: string
    unit: string
    priceNet: number
    dateChecked: string
    rationale: string
    partNumber?: string
    confidence?: number
  }
  evidence: {
    sourceUri: string
    title: string
    priceNet?: number
    unit?: string
    partNumber?: string
    minimalExcerpt?: string
  }
}

interface ApiErrorPayload {
  detail?: string | { message?: string; code?: string }
}

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init?: RequestInit,
  timeoutMs = 10_000
) {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)

  try {
    return await fetch(input, { ...init, signal: controller.signal })
  } finally {
    window.clearTimeout(timeout)
  }
}

function apiPath(path: string) {
  return `${API_BASE}${path}`
}

/** An API error that keeps the HTTP status and the backend's error code, so a
 * caller can tell an expected state apart from an unreachable service. The
 * bootstrap needs this to distinguish "this claim has no extracted invoice
 * yet" (409 WORKSPACE_NOT_READY) from "the API is down". */
export class ApiRequestError extends Error {
  readonly status: number
  readonly code: string | null

  constructor(message: string, status: number, code: string | null) {
    super(message)
    this.name = "ApiRequestError"
    this.status = status
    this.code = code
  }
}

async function apiError(response: Response) {
  let message = `API returned ${response.status}`
  let code: string | null = null
  try {
    const payload = (await response.json()) as ApiErrorPayload
    const detail = payload.detail
    if (typeof detail === "string") message = detail
    else if (detail) {
      if (detail.message) message = detail.message
      code = detail.code ?? null
    }
  } catch {
    // Preserve the status-based fallback when an upstream error is not JSON.
  }
  return new ApiRequestError(message, response.status, code)
}

async function requestJson<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 10_000
): Promise<T> {
  const response = await fetchWithTimeout(apiPath(path), init, timeoutMs)
  if (!response.ok) throw await apiError(response)
  return response.json() as Promise<T>
}

export function getApiErrorMessage(error: unknown) {
  if (error instanceof DOMException && error.name === "AbortError") {
    return "The API request timed out. Please try again."
  }
  return error instanceof Error ? error.message : "The API request failed."
}

export function fetchClaimWorkspace(
  caseReference: string,
  invoiceId?: string,
  p90ThresholdPct?: number
): Promise<ClaimWorkspace> {
  const params = new URLSearchParams()
  if (invoiceId) params.set("invoice_id", invoiceId)
  if (p90ThresholdPct !== undefined)
    params.set("p90_threshold_pct", String(p90ThresholdPct))
  const query = params.size ? `?${params.toString()}` : ""
  return requestJson(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/workspace${query}`
  )
}

export function fetchLinePriceEvidence(
  caseReference: string,
  lineId: string,
  p90ThresholdPct: number
): Promise<LinePriceEvidencePayload> {
  const query = new URLSearchParams({
    p90_threshold_pct: String(p90ThresholdPct),
  })
  return requestJson(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/lines/${encodeURIComponent(lineId)}/price-evidence?${query.toString()}`
  )
}

export function fetchClaimInvoices(
  caseReference: string,
  p90ThresholdPct = 10
): Promise<ClaimInvoiceSummary[]> {
  return requestJson(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/invoices?p90_threshold_pct=${encodeURIComponent(String(p90ThresholdPct))}`
  )
}

export function fetchEngineerAssessments(
  caseReference: string
): Promise<EngineerAssessmentPayload[]> {
  return requestJson(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/engineer-assessments`
  )
}

export function fetchClaimExtracts(
  caseReference: string
): Promise<ClaimExtractsPayload> {
  return requestJson(`/api/v1/claims/${encodeURIComponent(caseReference)}/extracts`)
}

export function fetchDataReadiness(): Promise<DataReadinessPayload> {
  return requestJson("/api/v1/readiness")
}

export function fetchHistoricalObservation(
  observationId: string
): Promise<HistoricalObservationPayload> {
  return requestJson(
    `/api/v1/historical-observations/${encodeURIComponent(observationId)}`
  )
}

export interface ComparisonRunPayload {
  status: string
  line_count: number
  mapped_count: number
  challenged_line_count: number
  ai_status: string
  ai_failure_code: string | null
}

export function runClaimComparison(
  caseReference: string
): Promise<ComparisonRunPayload> {
  return requestJson(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/compare`,
    { method: "POST" },
    120_000
  )
}

/** Plain-language explanation for an AI failure code, or null when the run was
 * fine (or AI is intentionally not configured). Shown as an informational
 * notice, never an error: the deterministic pipeline has already completed. */
export function friendlyAiUnavailableMessage(
  failureCode: string | null | undefined
): string | null {
  if (!failureCode) return null
  switch (failureCode) {
    case "LLM_RATE_LIMITED":
      return "The AI service reached its rate limit, so this run used the standard method only. Wait a minute and run it again to add AI assistance."
    case "LLM_TIMEOUT":
      return "The AI service took too long to respond, so this run used the standard method only. Running it again usually succeeds."
    case "LLM_AUTH_ERROR":
      return "The AI service rejected the configured key, so this run used the standard method only. Check CLAIM_GUARD_LLM_API_KEY in backend/.env."
    default:
      return "The AI service was unavailable, so this run used the standard method only. Results are still valid; run again later to add AI assistance."
  }
}

export function fetchBenchmarkDashboard(filters?: {
  caseReference?: string
  vehicleClass?: string
  ontologyItemId?: string
  minimumCount?: number
  challengeThresholdPct?: number
  sourceGroup?: "in_house" | "historical_claim"
}): Promise<BenchmarkDashboardPayload> {
  const query = new URLSearchParams()
  if (filters?.caseReference) query.set("case_reference", filters.caseReference)
  if (filters?.vehicleClass) query.set("vehicle_class", filters.vehicleClass)
  if (filters?.ontologyItemId)
    query.set("ontology_item_id", filters.ontologyItemId)
  if (filters?.minimumCount)
    query.set("minimum_count", String(filters.minimumCount))
  if (filters?.challengeThresholdPct !== undefined)
    query.set("challenge_threshold_pct", String(filters.challengeThresholdPct))
  if (filters?.sourceGroup) query.set("source_group", filters.sourceGroup)
  const suffix = query.size ? `?${query.toString()}` : ""
  return requestJson(`/api/v1/benchmarks/dashboard${suffix}`)
}

export interface ChallengeKnowledgeGraphPayload {
  caseReference: string
  storage: "neo4j" | "relational-fallback"
  summary: {
    mostChallengedRepairer: {
      id: string
      name: string
      invoiceCount: number
      challengeCount: number
      totalChallenge: number
    } | null
    mostChallengedItem: {
      id: string
      name: string
      invoiceCount: number
      challengeCount: number
      totalChallenge: number
    } | null
    challengedInvoiceCount: number
    potentialReduction: number
  }
  repairers: Array<{
    id: string
    name: string
    invoiceCount: number
    challengeCount: number
    totalChallenge: number
  }>
  items: Array<{
    id: string
    name: string
    invoiceCount: number
    challengeCount: number
    totalChallenge: number
  }>
  edges: Array<{
    id: string
    repairer: string
    itemId: string
    item: string
    invoiceCount: number
    challengeCount: number
    totalChallenge: number
    maximumChallenge: number
    evidence: Array<{
      lineId: string
      invoiceId: string
      invoiceNumber: string
      repairer: string
      description: string
      billedPrice: number
      supportedPrice: number
      challengeAmount: number
      inHouseP90: number | null
      historicalClaimsP90: number | null
      externalReferencePrice: number | null
      status: string
    }>
  }>
}

export function fetchChallengeKnowledgeGraph(
  caseReference: string,
  p90ThresholdPct?: number
): Promise<ChallengeKnowledgeGraphPayload> {
  const query = new URLSearchParams()
  if (p90ThresholdPct !== undefined)
    query.set("p90_threshold_pct", String(p90ThresholdPct))
  const suffix = query.size ? `?${query.toString()}` : ""
  return requestJson(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/knowledge-graph${suffix}`
  )
}

export function fetchBenchmarkObservations(
  ontologyItemId: string,
  vehicleClass?: string,
  sourceGroup?: "in_house" | "historical_claim"
): Promise<{ observations: BenchmarkObservationPayload[] }> {
  const query = new URLSearchParams()
  if (vehicleClass) query.set("vehicle_class", vehicleClass)
  if (sourceGroup) query.set("source_group", sourceGroup)
  const suffix = query.size ? `?${query.toString()}` : ""
  return requestJson(
    `/api/v1/benchmarks/${encodeURIComponent(ontologyItemId)}/observations${suffix}`
  )
}

/** One row of `GET /api/v1/claims`. The endpoint returns the full case payload;
 * only the fields the bootstrap needs are typed here. */
export interface ClaimListEntry {
  id: string
  case_reference: string
  status: string
  created_at: string
  invoice_count: number
}

/**
 * Every claim in the database, most recently created first (the backend
 * orders by `created_at` descending).
 *
 * The endpoint answers with a JSON array. A 200 carrying anything else is a
 * broken response, not an empty database, so it is raised as an API error
 * rather than being allowed to reach the screen as "the database holds no
 * claims" — a statement about the client's data that would simply be untrue.
 */
export async function fetchClaims(): Promise<ClaimListEntry[]> {
  const payload = await requestJson<unknown>("/api/v1/claims")
  if (!Array.isArray(payload)) {
    throw new ApiRequestError(
      "The claims list came back in a shape this app cannot read.",
      200,
      "MALFORMED_CLAIM_LIST"
    )
  }
  return payload as ClaimListEntry[]
}

/**
 * Which claim to open out of everything the database holds.
 *
 * `GET /claims` is ordered newest first, so `claims[0]` is the most recently
 * created case. Taking it unconditionally makes earlier work unreachable:
 * a reset — or any freshly created case — puts an empty stub in front of a
 * claim that may hold a batch of reviewed invoices, and there is no claim
 * picker to get back to it. Preferring the newest claim that actually holds
 * an invoice keeps that work reachable, and still lands on the fresh empty
 * case when that is the only thing there is.
 */
export function claimToOpen(claims: ClaimListEntry[]): ClaimListEntry | null {
  return (
    claims.find((claim) => (claim.invoice_count ?? 0) > 0) ?? claims[0] ?? null
  )
}

/**
 * The workspace endpoint's "this claim is not ready" answer.
 *
 * `backend/app/api/router.py` raises `409` with an object detail carrying
 * `code: "WORKSPACE_NOT_READY"`. `apiError` only reads `code` off an object
 * detail, so a plain-string 409 — from a proxy, or any handler that passes
 * `detail` as a string — arrives with `code === null`; that still has to
 * count as the same condition rather than being reported as an outage.
 */
function isWorkspaceNotReady(error: unknown): error is ApiRequestError {
  return (
    error instanceof ApiRequestError &&
    error.status === 409 &&
    (error.code === "WORKSPACE_NOT_READY" || error.code === null)
  )
}

/** The claim named in the URL no longer resolves (`404 Claim not found`). */
function isClaimGone(error: unknown): error is ApiRequestError {
  return error instanceof ApiRequestError && error.status === 404
}

/** Returned by `openClaimWorkspace` when the claim vanished under it. */
const CLAIM_GONE = Symbol("claim-gone")

async function openClaimWorkspace(
  entry: ClaimListEntry,
  p90ThresholdPct?: number
): Promise<WorkspaceBootstrap | typeof CLAIM_GONE> {
  const caseReference = entry.case_reference
  try {
    return {
      status: "ready",
      caseReference,
      workspace: await fetchClaimWorkspace(
        caseReference,
        undefined,
        p90ThresholdPct
      ),
    }
  } catch (error) {
    if (isClaimGone(error)) return CLAIM_GONE
    if (isWorkspaceNotReady(error)) {
      // The backend raises WORKSPACE_NOT_READY for *every* `ValueError`
      // escaping `build_claim_workspace`, not only "the claim has no
      // extracted invoice" — so the code alone does not license a screen
      // that states nothing has been extracted. The list row says whether
      // this claim holds any invoice at all; only when it holds none is that
      // statement true. Anything else is reported with the backend's own
      // words instead of a guess about the claim's contents.
      if (entry.invoice_count === 0) {
        return {
          status: "awaiting-documents",
          caseReference,
          message: error.message,
        }
      }
      return {
        status: "workspace-error",
        caseReference,
        message: error.message,
      }
    }
    return { status: "unavailable", message: getApiErrorMessage(error) }
  }
}

/**
 * Discover which claim to open instead of assuming a fixed case reference.
 *
 * The client asked for a clean slate: after a reset the database may hold no
 * claims at all, or a brand new claim with nothing uploaded against it yet.
 * Both are ordinary states, not failures, and neither may be papered over
 * with invented data — so each gets its own result the UI can render honestly.
 */
export async function bootstrapClaimWorkspace(
  p90ThresholdPct?: number
): Promise<WorkspaceBootstrap> {
  let claims: ClaimListEntry[]
  try {
    claims = await fetchClaims()
  } catch (error) {
    return { status: "unavailable", message: getApiErrorMessage(error) }
  }

  let entry = claimToOpen(claims)
  if (!entry) return { status: "no-claims" }

  let result = await openClaimWorkspace(entry, p90ThresholdPct)
  if (result !== CLAIM_GONE) return result

  // The claim disappeared between the list call and the workspace call. The
  // reset wipes every case and creates a fresh one, so losing the race is an
  // ordinary event — the API is healthy and saying it is down would be a lie.
  // Re-read the list once and open whatever is there now.
  try {
    claims = await fetchClaims()
  } catch (error) {
    return { status: "unavailable", message: getApiErrorMessage(error) }
  }

  entry = claimToOpen(claims)
  if (!entry) return { status: "no-claims" }

  result = await openClaimWorkspace(entry, p90ThresholdPct)
  if (result !== CLAIM_GONE) return result

  // Two claims in a row vanished as we reached for them. Report exactly that
  // rather than retrying forever or blaming the connection.
  return {
    status: "workspace-error",
    caseReference: entry.case_reference,
    message:
      "The claim list keeps changing while it is being opened, so no claim could be read.",
  }
}

export function confirmLiability(
  caseReference: string,
  input: {
    status: LiabilityStatus
    confirmedBy: string
    rationale: string
    splitLiabilityPercentage?: number
  }
) {
  return requestJson<{ challenge_issue_allowed: boolean }>(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/liability/confirm`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: input.status,
        confirmed_by: input.confirmedBy,
        rationale: input.rationale,
        split_liability_percentage: input.splitLiabilityPercentage,
      }),
    }
  )
}

export function correctInvoiceLine(lineId: string, input: LineCorrectionInput) {
  return requestJson(`/api/v1/invoice-lines/${encodeURIComponent(lineId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      actor: input.actor,
      reason: input.reason,
      raw_description: input.description,
      quantity: input.quantity,
      unit_price_net: input.unitPriceNet,
      line_total_net: input.lineTotalNet,
    }),
  })
}

export interface ManualLineInput {
  description: string
  quantity?: number
  unit?: string
  unitPriceNet?: number
  lineTotalNet: number
  vatRate?: number
  itemKind?: string
  partNumber?: string
  pageNumber?: number
  recordedBy: string
}

export function addManualInvoiceLine(
  caseReference: string,
  invoiceId: string,
  input: ManualLineInput
) {
  return requestJson(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/invoices/${encodeURIComponent(invoiceId)}/lines`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description: input.description,
        quantity: input.quantity,
        unit: input.unit,
        unit_price_net: input.unitPriceNet,
        line_total_net: input.lineTotalNet,
        vat_rate: input.vatRate,
        item_kind: input.itemKind ?? "part",
        part_number: input.partNumber,
        page_number: input.pageNumber,
        recorded_by: input.recordedBy,
      }),
    }
  )
}

export function decideExtractionLine(
  lineId: string,
  input: ExtractionDecisionInput
) {
  return requestJson(
    `/api/v1/invoice-lines/${encodeURIComponent(lineId)}/extraction-decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }
  )
}

export function recordSettlement(invoiceId: string, input: SettlementInput) {
  return requestJson(
    `/api/v1/invoices/${encodeURIComponent(invoiceId)}/settlements`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agreed_amount_net: input.agreedAmountNet,
        agreed_at: input.agreedAt,
        recorded_by: input.recordedBy,
        note: input.note,
        lines: input.lines.map((line) => ({
          line_item_id: line.lineItemId,
          agreed_amount_net: line.agreedAmountNet,
        })),
      }),
    }
  )
}

export function decideChallenge(
  challengeId: string,
  input: {
    actor: string
    approved: boolean
    rationale: string
    challengePriceNet?: number
  }
) {
  return requestJson(
    `/api/v1/challenge-results/${encodeURIComponent(challengeId)}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actor: input.actor,
        approved: input.approved,
        rationale: input.rationale,
        challenge_price_net: input.challengePriceNet,
      }),
    }
  )
}

export function startLineResearch(
  caseReference: string,
  lineId: string,
  input: ManualResearchInput
) {
  return requestJson<{ research_item_id: string }>(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/invoice-lines/${encodeURIComponent(lineId)}/research`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        requested_by: input.requestedBy,
        query_text: input.queryText,
        source_allow_list_version: input.sourceAllowListVersion,
        suggestion: {
          canonical_name: input.suggestion.canonicalName,
          item_type: input.suggestion.itemType,
          category: input.suggestion.category,
          unit: input.suggestion.unit,
          price_net: input.suggestion.priceNet,
          date_checked: input.suggestion.dateChecked,
          rationale: input.suggestion.rationale,
          part_number: input.suggestion.partNumber,
          confidence: input.suggestion.confidence,
          vat_basis: "net",
          price_scope: "unit",
          currency: "GBP",
          region: "UK",
        },
        evidence: [
          {
            source_uri: input.evidence.sourceUri,
            title: input.evidence.title,
            price_net: input.evidence.priceNet,
            unit: input.evidence.unit,
            part_number: input.evidence.partNumber,
            minimal_excerpt: input.evidence.minimalExcerpt,
            vat_basis: "net",
            currency: "GBP",
          },
        ],
      }),
    }
  )
}

export function approveResearchItem(
  researchItemId: string,
  input: { approvedBy: string; reviewerNote?: string }
) {
  return requestJson(
    `/api/v1/research-items/${encodeURIComponent(researchItemId)}/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        approved_by: input.approvedBy,
        reviewer_note: input.reviewerNote,
      }),
    }
  )
}

export function decideLineMapping(
  caseReference: string,
  lineId: string,
  input: MappingDecisionInput
) {
  return requestJson(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/invoice-lines/${encodeURIComponent(lineId)}/mapping-decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actor: input.actor,
        decision: input.decision,
        rationale: input.rationale,
        ontology_item_id: input.ontologyItemId,
        bundle_components: (input.bundleComponents ?? []).map((component) => ({
          ontology_item_id: component.ontologyItemId,
          allocated_net: component.allocatedNet,
          quantity: component.quantity,
          unit: component.unit,
        })),
      }),
    }
  )
}

export function finaliseClaim(caseReference: string, finalisedBy: string) {
  return requestJson(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/finalise`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        finalised_by: finalisedBy,
        note: "All positive challenge lines reviewed in ClaimGuard.",
      }),
    }
  )
}

export async function requestReport(
  format: ReportFormat,
  caseReference: string
) {
  const response = await fetchWithTimeout(
    apiPath(
      `/api/v1/claims/${encodeURIComponent(caseReference)}/reports/${format}`
    ),
    undefined,
    60_000
  )
  if (!response.ok) throw await apiError(response)
  return response.blob()
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function inHouseRepairCsvUrl() {
  return apiPath("/api/v1/admin/in-house-repair-data.csv")
}

export async function downloadInHouseRepairCsv() {
  const response = await fetchWithTimeout(
    inHouseRepairCsvUrl(),
    undefined,
    30_000
  )
  if (!response.ok) throw await apiError(response)
  downloadBlob(await response.blob(), "claimguard-in-house-repair-data.csv")
}
