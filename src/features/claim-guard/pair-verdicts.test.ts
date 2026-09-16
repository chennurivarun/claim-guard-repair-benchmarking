import { describe, expect, it } from "vitest"

import type { PairKeyVerdict } from "@/lib/api"
import { pairKeyBadgeText, summarisePairKeyVerdicts } from "./pair-verdicts"

// After the pairing change, `pair_confidence` is matched keys over *compared*
// keys and pairing compares only keys both documents print -- so every
// surviving pair scores 1.0. The five sample pairs moved from 33% to 100%, and
// a registration-only link rendered "100% pairing confidence" beside prose
// reading "weak pair: only the registration was comparable". The badge is what
// gets read, so it has to carry the denominator and the skipped keys instead.

function verdict(overrides: Partial<PairKeyVerdict>): PairKeyVerdict {
  return {
    key: "registration",
    label: "registration",
    state: "matched",
    compared: true,
    absent_on: null,
    placeholder_on: null,
    assessment_value: "A30DRY",
    invoice_value: "A30DRY",
    text: "registration exact match",
    ...overrides,
  }
}

const registrationMatched = verdict({})
const claimMatched = verdict({
  key: "claim_reference",
  label: "claim reference",
  text: "claim reference exact match",
})
const policyAbsentOnInvoice = verdict({
  key: "policy_number",
  label: "policy number",
  state: "not_compared",
  compared: false,
  absent_on: "invoice",
  invoice_value: null,
  text: "policy number not printed on the invoice",
})
const policyPlaceholder = verdict({
  key: "policy_number",
  label: "policy number",
  state: "placeholder",
  compared: false,
  absent_on: "invoice",
  placeholder_on: "assessment",
  assessment_value: "PH",
  invoice_value: null,
  text: "policy number is a placeholder on the assessment (PH)",
})

describe("the pairing badge reports a denominator, never a percentage", () => {
  it("says how many printed identities agree, out of how many were compared", () => {
    const summary = summarisePairKeyVerdicts([
      registrationMatched,
      claimMatched,
      policyAbsentOnInvoice,
    ])

    expect(summary.agreement).toBe("2 of 2 printed identities agree")
    expect(summary.headline).toBe(
      "2 of 2 printed identities agree · policy number not printed on the invoice"
    )
  })

  it("never prints a percentage for a weak, single-key pair", () => {
    const text = pairKeyBadgeText(
      [
        registrationMatched,
        verdict({
          key: "claim_reference",
          label: "claim reference",
          state: "not_compared",
          compared: false,
          absent_on: "both",
          text: "claim reference not printed on either document",
        }),
        policyPlaceholder,
      ],
      "paired"
    )

    // This is the pair that used to read "100% pairing confidence".
    expect(text).not.toContain("%")
    expect(text).toContain("1 of 1 printed identity agrees")
    expect(text).toContain("claim reference not printed on either document")
    expect(text).toContain("policy number is a placeholder on the assessment")
  })

  it("names the keys that were skipped, and why", () => {
    const summary = summarisePairKeyVerdicts([
      registrationMatched,
      policyPlaceholder,
    ])

    // The spec: "the UI must say which keys were compared and which were
    // skipped for absence". An empty box and a filled-in one that identifies
    // nothing are different facts and read differently.
    expect(summary.skipped).toEqual([
      "policy number is a placeholder on the assessment (PH)",
    ])
  })

  it("reports a conflict rather than swallowing it into the fraction", () => {
    const summary = summarisePairKeyVerdicts([
      registrationMatched,
      verdict({
        key: "claim_reference",
        label: "claim reference",
        state: "conflict",
        text: "claim reference conflict: assessment 123456/1 versus invoice 999/9",
      }),
    ])

    expect(summary.agreement).toBe("1 of 2 printed identities agree")
    expect(summary.conflicts).toEqual([
      "claim reference conflict: assessment 123456/1 versus invoice 999/9",
    ])
  })

  it("says so when nothing could be compared at all", () => {
    const summary = summarisePairKeyVerdicts([
      policyAbsentOnInvoice,
      verdict({
        key: "registration",
        label: "registration",
        state: "not_compared",
        compared: false,
        absent_on: "both",
        text: "registration not printed on either document",
      }),
    ])

    expect(summary.agreement).toBe("No printed identity could be compared")
    expect(summary.headline).not.toContain("%")
  })

  it("falls back to the status, not to a percentage, with no verdicts", () => {
    expect(pairKeyBadgeText(undefined, "paired")).toBe(
      "Paired · no per-key pairing evidence recorded"
    )
    expect(pairKeyBadgeText([], "unpaired")).toBe(
      "Not paired · no per-key pairing evidence recorded"
    )
  })
})
