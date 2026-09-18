import { describe, expect, it } from "vitest"

import type {
  CaseMappingPayload,
  MappingAssessmentRow,
  MappingInvoiceOption,
} from "./document-api"
import {
  assessmentIdentity,
  invoiceLabel,
  pairEvidence,
  scopeMapping,
  sortMappingRows,
} from "./mapping-review-rows"

// The mapping screen exists because the pairing engine refuses to guess: the
// unpaired rows are the ones nothing else in the product can rescue. These
// assertions are about the two things a handler reads before deciding -- what
// order the rows come in, and what the evidence beside each pairing says.

function row(overrides: Partial<MappingAssessmentRow>): MappingAssessmentRow {
  return {
    assessment_id: "assessment-1",
    document_id: "document-1",
    document_filename: "report.pdf",
    assessment_number: "AS-1",
    registration: "A30DRY",
    claim_reference: "245338996/1",
    policy_number: null,
    vehicle_make: "Audi",
    vehicle_model: "A3",
    intake_group: "live",
    pair_status: "paired",
    pair_source: "automatic",
    pair_confidence: 1,
    pair_reasons: ["registration exact match"],
    pair_key_verdicts: [
      {
        key: "registration",
        label: "registration",
        state: "matched",
        compared: true,
        absent_on: null,
        placeholder_on: null,
        assessment_value: "A30DRY",
        invoice_value: "A30DRY",
        text: "registration exact match",
      },
      {
        key: "claim_reference",
        label: "claim reference",
        state: "matched",
        compared: true,
        absent_on: null,
        placeholder_on: null,
        assessment_value: "245338996/1",
        invoice_value: "245338996/1",
        text: "claim reference exact match",
      },
      {
        key: "policy_number",
        label: "policy number",
        state: "not_compared",
        compared: false,
        absent_on: "invoice",
        placeholder_on: null,
        assessment_value: "PL739284",
        invoice_value: null,
        text: "policy number not printed on the invoice",
      },
    ],
    paired_invoice_id: "invoice-1",
    paired_invoice_number: "INV-1",
    manual_override: null,
    ...overrides,
  }
}

function invoice(
  overrides: Partial<MappingInvoiceOption>
): MappingInvoiceOption {
  return {
    invoice_id: "invoice-1",
    document_id: "document-9",
    document_filename: "DL_Repair_Invoice_format_1.docx",
    invoice_number: "343653726836/1~3538",
    supplier_name: "Acme Bodyshop",
    registration: "A30DRY",
    claim_reference: "245338996/1",
    policy_number: null,
    intake_group: "live",
    ...overrides,
  }
}

describe("row order", () => {
  it("puts the assessments nothing could pair first", () => {
    const rows = [
      row({ assessment_id: "auto" }),
      row({
        assessment_id: "unpaired",
        pair_status: "unpaired",
        paired_invoice_id: null,
        pair_reasons: ["Two assessments agree with this invoice equally well"],
      }),
      row({
        assessment_id: "manual",
        pair_source: "manual",
        pair_confidence: null,
        manual_override: {
          state: "linked",
          invoice_id: "invoice-1",
          invoice_number: "INV-1",
          actor: "pilot.handler",
          at: "2026-09-17T10:00:00+00:00",
          reason: null,
          applied: true,
        },
      }),
    ]

    expect(sortMappingRows(rows).map((entry) => entry.assessment_id)).toEqual([
      "unpaired",
      "manual",
      "auto",
    ])
  })

  it("keeps the payload's order within a group and does not mutate the input", () => {
    const rows = [
      row({ assessment_id: "first", pair_status: "unpaired" }),
      row({ assessment_id: "second", pair_status: "unpaired" }),
    ]

    expect(sortMappingRows(rows).map((entry) => entry.assessment_id)).toEqual([
      "first",
      "second",
    ])
    expect(rows.map((entry) => entry.assessment_id)).toEqual([
      "first",
      "second",
    ])
  })
})

describe("pairing evidence", () => {
  it("prints the denominator, never a percentage", () => {
    // Every automatic pair scores 1.0 by construction, so "100%" would say
    // nothing at all about how much evidence there actually was.
    const text = pairEvidence(row({}))

    expect(text).toContain("2 of 2 printed identities agree")
    expect(text).toContain("policy number not printed on the invoice")
    expect(text).not.toContain("%")
  })

  it("names the person behind a link they made by hand", () => {
    const text = pairEvidence(
      row({
        pair_source: "manual",
        pair_confidence: null,
        pair_reasons: ["Linked to this invoice by hand by the claims handler"],
        manual_override: {
          state: "linked",
          invoice_id: "invoice-1",
          invoice_number: "INV-1",
          actor: "pilot.handler",
          at: "2026-09-17T10:00:00+00:00",
          reason: "Confirmed against the paperwork",
          applied: true,
        },
      })
    )

    expect(text).toContain("Linked by hand by pilot.handler")
    expect(text).not.toContain("%")
  })

  it("tells an unpaired assessment why the rule refused", () => {
    expect(
      pairEvidence(
        row({
          pair_status: "unpaired",
          paired_invoice_id: null,
          pair_key_verdicts: [],
          pair_reasons: [
            "Two assessments agree with this invoice equally well; manual linkage required",
          ],
        })
      )
    ).toContain("manual linkage required")
  })
})

describe("how the documents are named", () => {
  it("falls back to the filename when the invoice prints no number", () => {
    expect(invoiceLabel(invoice({}))).toBe("343653726836/1~3538 · A30DRY")
    expect(invoiceLabel(invoice({ invoice_number: "  " }))).toBe(
      "DL_Repair_Invoice_format_1.docx · A30DRY"
    )
    expect(
      invoiceLabel(
        invoice({ invoice_number: null, document_filename: null, registration: null })
      )
    ).toBe("invoice-1")
  })

  it("says which identities the assessment did not print", () => {
    expect(assessmentIdentity(row({ policy_number: null }))).toEqual([
      "Assessment AS-1",
      "Registration A30DRY",
      "Claim 245338996/1",
      "Policy Not printed",
    ])
  })
})

// Per-source mapping review. The server is asked for one intake group, but
// the override endpoint answers with the mapping it has, and approving
// third party must never show -- or count -- an Aviva DLG row. So the screen
// keeps only its own group's rows and recounts from what is left.
describe("a mapping scoped to one source", () => {
  const payload: CaseMappingPayload = {
    case_reference: "CG-2026-0048",
    approval: {
      approved: false,
      approved_by: null,
      approved_at: null,
      approved_pairs: {},
    },
    invoices: [
      invoice({ invoice_id: "tp-inv", intake_group: "historical_claim" }),
      invoice({ invoice_id: "dlg-inv", intake_group: "in_house" }),
      invoice({ invoice_id: "old-inv", intake_group: null }),
    ],
    assessments: [
      row({ assessment_id: "tp-1", intake_group: "historical_claim" }),
      row({
        assessment_id: "tp-2",
        intake_group: "historical_claim",
        pair_status: "unpaired",
        paired_invoice_id: null,
      }),
      row({
        assessment_id: "dlg-1",
        intake_group: "in_house",
        pair_source: "manual",
      }),
    ],
    assessments_total: 3,
    paired: 2,
    unpaired: 1,
    manual: 1,
  }

  it("keeps only that source's assessments and invoices", () => {
    const scoped = scopeMapping(payload, "historical_claim")

    expect(scoped.assessments.map((r) => r.assessment_id)).toEqual([
      "tp-1",
      "tp-2",
    ])
    // A row the server did not tag is kept: the server was asked for this
    // group, so an untagged row is its answer, not another source's.
    expect(scoped.invoices.map((i) => i.invoice_id)).toEqual([
      "tp-inv",
      "old-inv",
    ])
  })

  it("recounts from the rows it kept", () => {
    const scoped = scopeMapping(payload, "historical_claim")

    expect(scoped.assessments_total).toBe(2)
    expect(scoped.paired).toBe(1)
    expect(scoped.unpaired).toBe(1)
    expect(scoped.manual).toBe(0)
  })

  it("leaves an unscoped mapping alone", () => {
    expect(scopeMapping(payload, undefined)).toBe(payload)
  })
})
