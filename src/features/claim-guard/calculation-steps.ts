import type { CalculationStep } from "./types"

/**
 * Pure helpers for rendering the server's operational price decision
 * (`InvoiceLine.calculation`, see backend/app/domain/price_decision.py
 * `decide_line_price`). Kept in a separate .ts module (rather than inline in
 * calculation-breakdown.tsx) so vitest — which only picks up `*.test.ts`, not
 * `*.tsx` — can exercise the normalization logic directly. Deliberately not
 * named `calculation-breakdown.ts`: a same-basename `.ts`/`.tsx` pair is an
 * ambiguous module specifier that `tsc -b`'s build-mode resolution picked
 * inconsistently from plain `tsc --noEmit`.
 */

/**
 * Order and de-duplicate calculation steps by their `step` number so the
 * panel renders deterministically even if the payload arrives out of order.
 * Returns an empty array (never null/undefined) when there is nothing to
 * show, so callers can render nothing without extra null checks.
 */
export function normalizeCalculationSteps(
  steps?: CalculationStep[] | null
): CalculationStep[] {
  if (!steps || steps.length === 0) return []
  const byStep = new Map<number, CalculationStep>()
  for (const step of steps) {
    if (step && typeof step.step === "number") {
      byStep.set(step.step, step)
    }
  }
  return [...byStep.values()].sort((a, b) => a.step - b.step)
}

/** A step is a pass/fail gate only when it explicitly carries `passed`. */
export function isGateStep(
  step: CalculationStep
): step is CalculationStep & { passed: boolean } {
  return step.passed !== undefined && step.passed !== null
}

/** Render-friendly text for a step's value; `null`/`undefined` become "—". */
export function formatStepValue(value: CalculationStep["value"]): string {
  if (value === null || value === undefined || value === "") return "—"
  return String(value)
}
