import { Badge } from "@/components/ui/badge"

import {
  formatStepValue,
  isGateStep,
  normalizeCalculationSteps,
} from "./calculation-steps"
import type { CalculationStep } from "./types"

/**
 * "How this price was decided" — renders the server's ordered `calculation`
 * breakdown for one invoice line (billed net → P90 evidence → external price
 * → weighting → evidence price → supported price → the two review gates →
 * status → VAT impact). Renders nothing when the line carries no breakdown
 * (e.g. no P90 benchmark signal), so callers can include it unconditionally.
 */
export function CalculationBreakdown({
  steps,
  title = "How this price was decided",
}: {
  steps?: CalculationStep[] | null
  title?: string
}) {
  const ordered = normalizeCalculationSteps(steps)
  if (ordered.length === 0) return null

  return (
    <div className="rounded-lg border">
      <div className="border-b bg-muted/30 px-4 py-2.5">
        <p className="text-sm font-medium">{title}</p>
      </div>
      <ol className="divide-y">
        {ordered.map((step) => {
          const gate = isGateStep(step)
          return (
            <li key={step.step} className="flex flex-col gap-1 px-4 py-2.5">
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-medium">
                  <span className="mr-2 text-xs text-muted-foreground tabular-nums">
                    {step.step}.
                  </span>
                  {step.label}
                </p>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="text-sm font-medium tabular-nums">
                    {formatStepValue(step.value)}
                  </span>
                  {gate ? (
                    <Badge variant={step.passed ? "success" : "destructive"}>
                      {step.passed ? "Pass" : "Fail"}
                    </Badge>
                  ) : null}
                </div>
              </div>
              {step.detail ? (
                <p className="pl-6 text-xs leading-5 text-muted-foreground">
                  {step.detail}
                </p>
              ) : null}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
