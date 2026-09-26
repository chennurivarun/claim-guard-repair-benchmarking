import type { SectionBreakdownPayload } from "@/lib/api"

import { requestJson, type IntakeGroup } from "./document-api"

/** The benchmarks-and-challenges endpoints, typed exactly as the contract in
 * `client-formats/BUILD_SPEC_2026-09-18_benchmarks-and-challenges.md` writes
 * them. Money arrives as decimal strings and stays a string here; the
 * screens parse it once, at the point they print it. Nothing in this file
 * fills a missing field in: a P90 the server does not have is `null`, and
 * the screen must say "No data", never £0.00. */

/** The two bodies of history a new invoice is judged against. D1 of the
 * spec: they are the two upload buckets that already exist, relabelled --
 * `third_party` is `historical_claim`, `aviva_dlg` is `in_house`. */
export type BenchmarkSource = "third_party" | "aviva_dlg"

export const BENCHMARK_SOURCES: Record<
  BenchmarkSource,
  { intakeGroup: IntakeGroup; label: string; shortLabel: string }
> = {
  third_party: {
    intakeGroup: "historical_claim",
    label: "Insurer Third Party invoices",
    shortLabel: "Third party",
  },
  aviva_dlg: {
    intakeGroup: "in_house",
    label: "EXL/ In house Benchmark invoices",
    shortLabel: "In-house",
  },
}

/** Where a vehicle's category came from (D2): the seeded lookup, the AI
 * fallback, or neither -- in which case the category is `Unknown`, which is
 * benchmarked within itself and shown, never skipped. */
export type VehicleCategorySource = "lookup" | "ai" | "unknown"

/** Which document a line was read from. */
export type LineOrigin = "invoice" | "engineer_assessment"

/** One contributing row behind a P90. */
export interface BenchmarkEvidenceRow {
  invoice_id: string
  invoice_number: string | null
  document_filename: string | null
  vehicle_make: string | null
  vehicle_model: string | null
  registration: string | null
  description: string
  amount: string
  origin: LineOrigin
  source_line_id: string
}

export interface VehicleCategorySummary {
  category: string
  invoice_count: number
  source: VehicleCategorySource
}

/** P90 per repair item per vehicle category, for one source. */
export interface BenchmarkRow {
  vehicle_category: string
  repair_item: string
  repair_item_key: string
  line_item_type: string | null
  observations: number
  p90: string
  median: string
  min: string
  max: string
  evidence: BenchmarkEvidenceRow[]
}

/** `GET /claims/{ref}/benchmarks?source=…`. */
export interface SourceBenchmarksPayload {
  source: BenchmarkSource
  intake_group: IntakeGroup
  label: string
  invoice_count: number
  threshold_pct: string
  vehicle_categories: VehicleCategorySummary[]
  rows: BenchmarkRow[]
}

/** One line measured against one source's P90. `available: false` means the
 * source holds no observation for this repair item in this category. */
export interface AnalysisBenchmark {
  available: boolean
  p90: string | null
  observations: number
  above_p90: boolean
  violated: boolean
  difference: string | null
  difference_pct: string | null
  evidence: BenchmarkEvidenceRow[]
}

/** High = both benchmarks violated, Medium = one, Low = above a P90 but
 * inside the valuation rule (D3). `null` is no challenge at all. */
export type ChallengeLevel = "high" | "medium" | "low"

export interface AnalysisChallenge {
  /** True for high and medium only. */
  is_challenge: boolean
  level: ChallengeLevel | null
  justified_amount: string | null
  challenge_amount: string
  reason: string
}

export interface AnalysisLine {
  line_id: string
  origin: LineOrigin
  line_item_type: string | null
  description: string
  repair_item: string | null
  amount: string
  benchmarks: Record<BenchmarkSource, AnalysisBenchmark>
  challenge: AnalysisChallenge
}

export interface AnalysisInvoice {
  id: string
  invoice_number: string | null
  vehicle_make: string | null
  vehicle_model: string | null
  vehicle_category: string
  vehicle_category_source: VehicleCategorySource
  registration: string | null
  paired_assessment_number: string | null
}

export interface LiveInvoiceOption {
  id: string
  invoice_number: string | null
  registration: string | null
}

/** `GET /claims/{ref}/benchmark-analysis`. */
export interface BenchmarkAnalysisPayload {
  invoice: AnalysisInvoice
  live_invoices: LiveInvoiceOption[]
  threshold_pct: string
  minimum_challenge_amount: string
  lines: AnalysisLine[]
  section_breakdowns: SectionBreakdownPayload[]
  totals: {
    line_count: number
    challenge_count: number
    by_level: Record<ChallengeLevel, number>
    total_challenge_amount: string
  }
}

/** `POST /claims/{ref}/challenge-email`. A draft: the server never sends it. */
export interface ChallengeEmailDraft {
  subject: string
  body: string
  generated_by: "ai" | "template"
  lines: AnalysisLine[]
  total_challenge_amount: string
}

function claimPath(caseReference: string, rest: string) {
  return `/api/v1/claims/${encodeURIComponent(caseReference)}${rest}`
}

export function fetchSourceBenchmarks(
  caseReference: string,
  source: BenchmarkSource
) {
  const query = new URLSearchParams({ source })
  return requestJson<SourceBenchmarksPayload>(
    claimPath(caseReference, `/benchmarks?${query.toString()}`),
    undefined,
    60_000
  )
}

/** With no invoice the server picks the most recent `live` invoice. */
export function fetchBenchmarkAnalysis(
  caseReference: string,
  invoiceId?: string
) {
  const query = invoiceId
    ? `?${new URLSearchParams({ invoice_id: invoiceId }).toString()}`
    : ""
  return requestJson<BenchmarkAnalysisPayload>(
    claimPath(caseReference, `/benchmark-analysis${query}`),
    undefined,
    60_000
  )
}

/** Drafts the email for the selected lines. The server writes one audit
 * event recording which lines were drafted, and sends nothing. */
export function draftChallengeEmail(
  caseReference: string,
  input: { invoiceId: string; lineIds: string[]; recipient?: string }
) {
  return requestJson<ChallengeEmailDraft>(
    claimPath(caseReference, "/challenge-email"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        invoice_id: input.invoiceId,
        line_ids: input.lineIds,
        ...(input.recipient ? { recipient: input.recipient } : {}),
      }),
    },
    120_000
  )
}
