import { describe, expect, it } from "vitest"

import { applyP90PolicyToLine } from "./p90-policy"
import type { InvoiceLine } from "./types"

function line(overrides: Partial<InvoiceLine> = {}): InvoiceLine {
  return {
    id: "line-1",
    description: "Right door mirror",
    kind: "Part",
    quantity: 1,
    unit: "each",
    unitPrice: 200,
    currentTotal: 200,
    vatRate: 20,
    historicalCount: 4,
    challenge: 0,
    extractionConfidence: 0.98,
    mappingStatus: "MATCH",
    comparisonStatus: "WITHIN",
    rationale: "",
    p90Benchmark: {
      category: "Door mirror",
      currentPrice: 200,
      historicalCount: 4,
      historicalMean: 100,
      p90: 100,
      difference: 100,
      percentageDifference: 100,
      decision: "Challenge",
      challenged: true,
      explanation: "Earlier matching invoices establish P90.",
      observations: [],
      method: "Nearest-rank P90",
      currentInvoiceExcluded: true,
    },
    ...overrides,
  }
}

describe("applyP90PolicyToLine", () => {
  it("weights P90 at 70% and approved external evidence at 30%", () => {
    const result = applyP90PolicyToLine(line({ ontologyTotal: 160 }), 5)

    expect(result.recommended).toBe(118)
    expect(result.challenge).toBe(82)
    expect(result.challengeVat).toBe(16.4)
    expect(result.evidenceRationale).toContain("70% weight")
    expect(result.evidenceRationale).toContain("30%")
  })

  it("uses P90 alone when external evidence is unavailable", () => {
    const result = applyP90PolicyToLine(line(), 5)

    expect(result.recommended).toBe(100)
    expect(result.challenge).toBe(100)
    expect(result.evidenceRationale).toContain(
      "No approved external price is available"
    )
  })

  it("does not create a challenge unless both policy gates are exceeded", () => {
    const result = applyP90PolicyToLine(
      line({ currentTotal: 122, unitPrice: 122, ontologyTotal: 160 }),
      5
    )

    expect(result.recommended).toBe(118)
    expect(result.challenge).toBe(0)
    expect(result.comparisonStatus).toBe("WITHIN")
  })
})
