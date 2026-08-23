import { demoWorkspace } from "@/features/claim-guard/demo-data"
import type {
  ApiWorkspaceResult,
  ClaimWorkspace,
  LiabilityStatus,
} from "@/features/claim-guard/types"

const configuredApiBase = import.meta.env.VITE_API_URL as string | undefined
const API_BASE = (configuredApiBase?.trim() || "").replace(/\/+$/, "")
const DEFAULT_CASE_REFERENCE = "CG-2026-0048"

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

export interface DataReadinessPayload {
  ready: boolean
  ontology_items: number
  historical_claims: number
  issues: string[]
}

export interface ClaimInvoiceSummary {
  id: string
  invoice_number: string | null
  invoice_date: string | null
  document_id?: string
  document_filename: string
  supplier_name: string | null
  totals: {
    gross: number | null
  }
  challenge_review: {
    positive: number
    approved: number
    rejected: number
    unresolved: number
  }
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

async function apiError(response: Response) {
  let message = `API returned ${response.status}`
  try {
    const payload = (await response.json()) as ApiErrorPayload
    const detail = payload.detail
    if (typeof detail === "string") message = detail
    else if (detail?.message) message = detail.message
  } catch {
    // Preserve the status-based fallback when an upstream error is not JSON.
  }
  return new Error(message)
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
  caseReference = DEFAULT_CASE_REFERENCE,
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

export function fetchClaimInvoices(
  caseReference = DEFAULT_CASE_REFERENCE
): Promise<ClaimInvoiceSummary[]> {
  return requestJson(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/invoices`
  )
}

export function fetchEngineerAssessments(
  caseReference = DEFAULT_CASE_REFERENCE
): Promise<EngineerAssessmentPayload[]> {
  return requestJson(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/engineer-assessments`
  )
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

export function runClaimComparison(caseReference: string) {
  return requestJson(
    `/api/v1/claims/${encodeURIComponent(caseReference)}/compare`,
    { method: "POST" },
    120_000
  )
}

export function fetchBenchmarkDashboard(filters?: {
  caseReference?: string
  vehicleClass?: string
  ontologyItemId?: string
  minimumCount?: number
  challengeThresholdPct?: number
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
  const suffix = query.size ? `?${query.toString()}` : ""
  return requestJson(`/api/v1/benchmarks/dashboard${suffix}`)
}

export function fetchBenchmarkObservations(
  ontologyItemId: string,
  vehicleClass?: string
): Promise<{ observations: BenchmarkObservationPayload[] }> {
  const query = new URLSearchParams()
  if (vehicleClass) query.set("vehicle_class", vehicleClass)
  const suffix = query.size ? `?${query.toString()}` : ""
  return requestJson(
    `/api/v1/benchmarks/${encodeURIComponent(ontologyItemId)}/observations${suffix}`
  )
}

export async function loadClaimWorkspace(
  p90ThresholdPct?: number
): Promise<ApiWorkspaceResult> {
  try {
    return {
      workspace: await fetchClaimWorkspace(
        undefined,
        undefined,
        p90ThresholdPct
      ),
      mode: "api",
    }
  } catch (error) {
    return {
      workspace: demoWorkspace,
      mode: "demo",
      errorMessage: getApiErrorMessage(error),
    }
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
  caseReference = DEFAULT_CASE_REFERENCE
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

export function downloadDemoJson() {
  const blob = new Blob([JSON.stringify(demoWorkspace, null, 2)], {
    type: "application/json",
  })
  downloadBlob(blob, "claimguard-CG-2026-0048-audit.json")
}
