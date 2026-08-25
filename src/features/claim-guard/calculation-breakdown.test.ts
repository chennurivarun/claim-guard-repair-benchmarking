import { describe, expect, it } from "vitest"

import {
  formatStepValue,
  isGateStep,
  normalizeCalculationSteps,
} from "./calculation-steps"
import type { CalculationStep } from "./types"

describe("normalizeCalculationSteps", () => {
  it("returns an empty array for undefined, null, or empty input", () => {
    expect(normalizeCalculationSteps(undefined)).toEqual([])
    expect(normalizeCalculationSteps(null)).toEqual([])
    expect(normalizeCalculationSteps([])).toEqual([])
  })

  it("sorts steps by their step number", () => {
    const steps: CalculationStep[] = [
      { step: 2, label: "P90 benchmark", value: "500.00", detail: "d2" },
      { step: 1, label: "Billed net", value: "600.00", detail: "d1" },
      { step: 3, label: "External price", value: null, detail: "d3" },
    ]
    expect(normalizeCalculationSteps(steps).map((s) => s.step)).toEqual([
      1, 2, 3,
    ])
  })

  it("de-duplicates by step number, keeping the last one seen", () => {
    const steps: CalculationStep[] = [
      { step: 1, label: "Billed net (stale)", value: "1.00", detail: "" },
      { step: 1, label: "Billed net", value: "600.00", detail: "" },
    ]
    const result = normalizeCalculationSteps(steps)
    expect(result).toHaveLength(1)
    expect(result[0].label).toBe("Billed net")
  })

  it("ignores malformed entries without a numeric step", () => {
    const steps = [
      { step: 1, label: "Billed net", value: "600.00", detail: "" },
      { label: "Missing step number", value: "x", detail: "" },
    ] as CalculationStep[]
    expect(normalizeCalculationSteps(steps)).toHaveLength(1)
  })
})

describe("isGateStep", () => {
  it("is true only when passed is explicitly boolean", () => {
    expect(
      isGateStep({ step: 7, label: "Percentage gate", passed: true })
    ).toBe(true)
    expect(isGateStep({ step: 8, label: "Absolute gate", passed: false })).toBe(
      true
    )
    expect(isGateStep({ step: 1, label: "Billed net" })).toBe(false)
    expect(isGateStep({ step: 1, label: "Billed net", passed: null })).toBe(
      false
    )
  })
})

describe("formatStepValue", () => {
  it("renders an em dash for null, undefined, or empty values", () => {
    expect(formatStepValue(null)).toBe("—")
    expect(formatStepValue(undefined)).toBe("—")
    expect(formatStepValue("")).toBe("—")
  })

  it("stringifies numbers and passes through strings", () => {
    expect(formatStepValue(600)).toBe("600")
    expect(formatStepValue("50% in-house / 30% claims / 20% external")).toBe(
      "50% in-house / 30% claims / 20% external"
    )
  })
})
