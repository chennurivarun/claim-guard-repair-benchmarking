import { MINIMUM_CHALLENGE_AMOUNT } from "./shared"
import type { ClaimWorkspace, InvoiceLine } from "./types"

function money(value: number) {
  return Math.round((value + Number.EPSILON) * 100) / 100
}

/**
 * Combine the uploaded-invoice P90 with the governed ontology/history result.
 * The higher reliable support price is used so the operational challenge never
 * claims a larger reduction than either evidence stream supports.
 */
export function applyP90PolicyToLine(
  line: InvoiceLine,
  thresholdPct: number
): InvoiceLine {
  const benchmark = line.p90Benchmark
  if (!benchmark) return line

  const governedBenchmark =
    line.governedBenchmarkSource &&
    line.governedBenchmarkSource !== "none" &&
    line.governedBenchmark !== undefined &&
    line.governedBenchmark !== null &&
    Number.isFinite(line.governedBenchmark) &&
    line.governedBenchmark > 0
      ? line.governedBenchmark
      : null
  const evidenceCeiling = Math.max(
    benchmark.p90,
    governedBenchmark ?? benchmark.p90
  )
  const supportedPrice = money(Math.min(line.currentTotal, evidenceCeiling))
  const difference = money(Math.max(0, line.currentTotal - supportedPrice))
  const percentageDifference =
    supportedPrice > 0 ? (difference / supportedPrice) * 100 : 0
  const challenged =
    percentageDifference > thresholdPct &&
    difference >= MINIMUM_CHALLENGE_AMOUNT
  const challenge = challenged ? difference : 0
  const challengeVat = challenged
    ? money((challenge * line.vatRate) / 100)
    : 0
  const governedExplanation = governedBenchmark
    ? `Governed ${line.governedBenchmarkSource?.replaceAll("_", " ")} support is £${governedBenchmark.toFixed(2)} (${line.governedBenchmarkFormula ?? "persisted ontology/history policy"}).`
    : "No separate governed support price passed its reliability checks; ontology and historical-claim evidence remains visible for review."
  const thresholdExplanation = challenged
    ? `${benchmark.explanation} ${governedExplanation} The conservative supported price is £${supportedPrice.toFixed(2)}, so the £${challenge.toFixed(2)} difference exceeds the ${thresholdPct}% and £${MINIMUM_CHALLENGE_AMOUNT.toFixed(2)} review gates.`
    : `${benchmark.explanation} ${governedExplanation} The conservative supported price is £${supportedPrice.toFixed(2)} and does not exceed both the ${thresholdPct}% and £${MINIMUM_CHALLENGE_AMOUNT.toFixed(2)} review gates.`

  return {
    ...line,
    historicalCount: benchmark.historicalCount,
    recommended: supportedPrice,
    challenge,
    challengeVat,
    comparisonStatus: challenged ? "CHALLENGE" : "WITHIN",
    rationale: thresholdExplanation,
    evidenceRationale:
      `Final support uses the higher of P90 (£${benchmark.p90.toFixed(2)}) and the reliable governed price${governedBenchmark ? ` (£${governedBenchmark.toFixed(2)})` : " (not available)"}. ` +
      `${benchmark.method}; ${benchmark.historicalCount} earlier matching invoice ` +
      `price${benchmark.historicalCount === 1 ? "" : "s"}; current invoice excluded. The mapping model selects a bounded repair category and never supplies a price.`,
  }
}

export function applyP90Policy(
  workspace: ClaimWorkspace,
  thresholdPct: number
): ClaimWorkspace {
  const lines = workspace.lines.map((line) =>
    applyP90PolicyToLine(line, thresholdPct)
  )
  const reviewable = lines.filter(
    (line) => line.challenge > 0 && line.challengeStatus !== "rejected"
  )
  const challengeAmount = money(
    reviewable.reduce((total, line) => total + line.challenge, 0)
  )
  const vatImpact = money(
    reviewable.reduce((total, line) => total + (line.challengeVat ?? 0), 0)
  )
  const invoiceNet = workspace.invoice.netIncludingMot

  return {
    ...workspace,
    lines,
    summary: {
      ...workspace.summary,
      challengePrice: money(Math.max(invoiceNet - challengeAmount, 0)),
      challengeAmount,
      vatImpact,
      grossEffect: money(challengeAmount + vatImpact),
      challengePercentage:
        invoiceNet > 0 ? money((challengeAmount / invoiceNet) * 100) : 0,
    },
  }
}
