import { MINIMUM_CHALLENGE_AMOUNT } from "./shared"
import type { ClaimWorkspace, InvoiceLine } from "./types"

function money(value: number) {
  return Math.round((value + Number.EPSILON) * 100) / 100
}

/**
 * Combine the uploaded-invoice P90 with an approved external price.
 * The current interim policy weights benchmark evidence 70% and external
 * evidence 30%; P90 stands alone when no external price is available.
 */
export function applyP90PolicyToLine(
  line: InvoiceLine,
  thresholdPct: number
): InvoiceLine {
  const benchmark = line.p90Benchmark
  if (!benchmark) return line

  const externalPrice =
    line.ontologyTotal !== undefined &&
    line.ontologyTotal !== null &&
    Number.isFinite(line.ontologyTotal) &&
    line.ontologyTotal > 0
      ? line.ontologyTotal
      : null
  const evidencePrice = money(
    externalPrice === null
      ? benchmark.p90
      : benchmark.p90 * 0.7 + externalPrice * 0.3
  )
  const supportedPrice = money(Math.min(line.currentTotal, evidencePrice))
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
  const priceExplanation = externalPrice
    ? `The support price applies 70% weight to the uploaded-invoice P90 (£${benchmark.p90.toFixed(2)}) and 30% to the approved external price (£${externalPrice.toFixed(2)}).`
    : `No approved external price is available, so the uploaded-invoice P90 of £${benchmark.p90.toFixed(2)} is used.`
  const thresholdExplanation = challenged
    ? `${benchmark.explanation} ${priceExplanation} The supported price is £${supportedPrice.toFixed(2)}, so the £${challenge.toFixed(2)} difference exceeds the ${thresholdPct}% and £${MINIMUM_CHALLENGE_AMOUNT.toFixed(2)} review gates.`
    : `${benchmark.explanation} ${priceExplanation} The supported price is £${supportedPrice.toFixed(2)} and does not exceed both the ${thresholdPct}% and £${MINIMUM_CHALLENGE_AMOUNT.toFixed(2)} review gates.`

  return {
    ...line,
    historicalCount: benchmark.historicalCount,
    recommended: supportedPrice,
    challenge,
    challengeVat,
    comparisonStatus: challenged ? "CHALLENGE" : "WITHIN",
    rationale: thresholdExplanation,
    evidenceRationale:
      `${priceExplanation} ` +
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
