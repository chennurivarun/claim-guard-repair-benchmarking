import type {
  AnalysisBenchmark,
  AnalysisLine,
  ChallengeEmailDraft,
  ChallengeLevel,
  VehicleCategorySource,
} from "./benchmark-api"
import { formatMoney } from "./format"

/** The pure rules behind Benchmark computation and Benchmark analysis: how a
 * figure is printed, how an Unknown category is recognised, what colour a
 * benchmark cell is, which order the lines come in, and what the total
 * challenge amount counts. Kept out of the screen files so each rule can be
 * asserted without rendering, and because the fast-refresh lint rule keeps a
 * component file to components. */

export function toNumber(value: string | number | null | undefined) {
  if (value == null || value === "") return null
  const parsed = typeof value === "number" ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

/** Money from the API's decimal strings. A missing figure is a dash, never
 * £0.00 -- zero is a price, absence is not. */
export function money(value: string | number | null | undefined) {
  const numeric = toNumber(value)
  return numeric == null ? "—" : formatMoney(numeric)
}

/** "n = 3". Printed beside every P90 so a P90 from one observation can
 * never be read as a population (the P90 of one value is that value). */
export function observationsLabel(observations: number) {
  return `n = ${observations}`
}

const CATEGORY_SOURCE_LABELS: Record<VehicleCategorySource, string> = {
  lookup: "From the lookup",
  ai: "AI-assigned",
  unknown: "Not recognised",
}

export function categorySourceLabel(source: VehicleCategorySource) {
  return CATEGORY_SOURCE_LABELS[source] ?? source
}

/** D2: a vehicle whose make and model neither the lookup nor the AI could
 * place is benchmarked in its own `Unknown` category. That category must
 * read as an unknown, never as a vehicle class, so it is recognised by name
 * *or* by its source -- either alone is enough. */
export function isUnknownCategory(
  category: string | null | undefined,
  source?: VehicleCategorySource | null
) {
  return (
    source === "unknown" ||
    !category ||
    category.trim().toLowerCase() === "unknown"
  )
}

export type BenchmarkCellState = "no-data" | "violated" | "above" | "within"

/** Red is `violated` (beyond the P90 by more than the threshold and at least
 * £5); amber is `above` (over the P90 but inside that rule); `no-data` is a
 * source with no observation for this repair item in this category. */
export function benchmarkCellState(benchmark: AnalysisBenchmark): BenchmarkCellState {
  if (!benchmark.available || toNumber(benchmark.p90) == null) return "no-data"
  if (benchmark.violated) return "violated"
  if (benchmark.above_p90) return "above"
  return "within"
}

/** "Firstly from invoice, then from assessment." Each document's own order
 * is kept as the server sent it. */
export function documentOrder(lines: AnalysisLine[]): AnalysisLine[] {
  return [
    ...lines.filter((line) => line.origin === "invoice"),
    ...lines.filter((line) => line.origin !== "invoice"),
  ]
}

const LEVEL_RANK: Record<ChallengeLevel | "none", number> = {
  high: 0,
  medium: 1,
  low: 2,
  none: 3,
}

function levelRank(line: AnalysisLine) {
  return LEVEL_RANK[line.challenge.level ?? "none"]
}

/** High, medium, low, none; within a level the larger challenge amount
 * first, and after that document order (invoice before engineer
 * assessment), so ties never shuffle. */
export function sortByChallengeLevel(lines: AnalysisLine[]): AnalysisLine[] {
  return documentOrder(lines)
    .map((line, index) => ({ line, index }))
    .sort(
      (a, b) =>
        levelRank(a.line) - levelRank(b.line) ||
        (toNumber(b.line.challenge.challenge_amount) ?? 0) -
          (toNumber(a.line.challenge.challenge_amount) ?? 0) ||
        a.index - b.index
    )
    .map((entry) => entry.line)
}

/** A challenge is a red line: High or Medium. Low is shown, never counted. */
export function isChallenge(line: AnalysisLine) {
  return line.challenge.level === "high" || line.challenge.level === "medium"
}

export interface ChallengeSummary {
  total: number
  counts: Record<ChallengeLevel, number>
  challengeCount: number
}

/** The total challenge amount, from the lines on screen rather than from the
 * payload's `totals`: whatever the table shows is what the total adds up,
 * and a Low line's distance above P90 is never in it. */
export function challengeSummary(lines: AnalysisLine[]): ChallengeSummary {
  const counts: Record<ChallengeLevel, number> = { high: 0, medium: 0, low: 0 }
  let total = 0
  // Membership is decided by `level`, never by `is_challenge` or by the
  // amount: a Low line is out of the total whatever the payload carries.
  for (const line of lines) {
    const level = line.challenge.level
    if (level) counts[level] += 1
    if (isChallenge(line)) total += toNumber(line.challenge.challenge_amount) ?? 0
  }
  return {
    total: Math.round(total * 100) / 100,
    counts,
    challengeCount: counts.high + counts.medium,
  }
}

/** How far a Low line sits above the P90 it exceeds -- the larger distance
 * if it is above both. Shown, never added to the total. */
export function lowLineDistance(line: AnalysisLine): number | null {
  const distances = Object.values(line.benchmarks)
    .filter((benchmark) => benchmark.above_p90)
    .map((benchmark) => toNumber(benchmark.difference))
    .filter((value): value is number => value != null)
  return distances.length ? Math.max(...distances) : null
}

/** Who wrote the draft, said honestly. The AI path is only trusted because
 * the server discards any AI prose that introduces a figure not in the
 * analysis and falls back to the template. */
export function generatedByLabel(generatedBy: ChallengeEmailDraft["generated_by"]) {
  return generatedBy === "ai"
    ? "AI-written; every figure checked against the analysis"
    : "Written from a template"
}

/** The "Open in email app" link. The handler's own mail client sends it, or
 * does not -- ClaimGuard never does. */
export function mailtoHref(subject: string, body: string, to = "") {
  return `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
}
