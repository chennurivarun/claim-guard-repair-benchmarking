import type { IntakeGroup } from "./document-api"
import type { ScreenId } from "./types"

/** Which source each of Neha's nine screens serves, and which step of that
 * source's flow it is. The screens are built once and used three times
 * (§4.2: "build once, use twice"); this table is the only place a screen id
 * turns into an `intake_group`, so a new source is one row here rather than
 * a fork of every screen. */

export type SourceStep = "upload" | "intelligence" | "benchmarks" | "analysis"

export interface ScreenScope {
  step: SourceStep
  intakeGroup: IntakeGroup
}

const SCREEN_SCOPES: Partial<Record<ScreenId, ScreenScope>> = {
  "tp-upload": { step: "upload", intakeGroup: "historical_claim" },
  "tp-intelligence": { step: "intelligence", intakeGroup: "historical_claim" },
  "tp-benchmarks": { step: "benchmarks", intakeGroup: "historical_claim" },
  "dlg-upload": { step: "upload", intakeGroup: "in_house" },
  "dlg-intelligence": { step: "intelligence", intakeGroup: "in_house" },
  "dlg-benchmarks": { step: "benchmarks", intakeGroup: "in_house" },
  "new-invoice-upload": { step: "upload", intakeGroup: "live" },
  "new-invoice-intelligence": { step: "intelligence", intakeGroup: "live" },
  "benchmark-analysis": { step: "analysis", intakeGroup: "live" },
}

/** Null for every screen outside her structure (the Advanced tools). */
export function screenScope(screen: ScreenId): ScreenScope | null {
  return SCREEN_SCOPES[screen] ?? null
}

/** The screen for one step of one source -- e.g. where an upload goes once
 * its batch has landed. */
export function sourceScreen(
  intakeGroup: IntakeGroup,
  step: SourceStep
): ScreenId {
  const match = (Object.entries(SCREEN_SCOPES) as Array<[ScreenId, ScreenScope]>)
    .find(
      ([, scope]) => scope.intakeGroup === intakeGroup && scope.step === step
    )
  if (!match) throw new Error(`No ${step} screen for ${intakeGroup}.`)
  return match[0]
}

/** The bucket names she uses. D1: the two existing upload buckets relabelled,
 * not duplicated. */
export const INTAKE_GROUP_LABELS: Record<IntakeGroup, string> = {
  historical_claim: "Third party insured invoices",
  in_house: "Aviva DLG invoices",
  live: "New invoice",
}

/** Which upload buckets the intake screen offers. A scoped screen offers its
 * own bucket and nothing else; the unscoped Advanced tools variants keep
 * what they always offered. */
export function intakeGroupsFor({
  setup,
  scope,
}: {
  setup: boolean
  scope?: IntakeGroup
}): IntakeGroup[] {
  if (scope) return [scope]
  return setup ? ["historical_claim", "in_house"] : ["live"]
}
