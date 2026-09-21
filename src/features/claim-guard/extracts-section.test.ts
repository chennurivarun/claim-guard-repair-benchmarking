import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { TooltipProvider } from "@/components/ui/tooltip"
import type {
  AssessmentExtractPayload,
  ClaimExtractsPayload,
  InvoiceExtractPayload,
  SectionBreakdownPayload,
} from "@/lib/api"
import {
  AssessmentExtractsTable,
  AssessmentLinesTable,
  ExtractsSection,
  InvoiceExtractsTable,
  SectionBreakdownDetail,
} from "./extracts-section"

// Formats 1 and 7 both print invoice number "343653726836/1~3538" -- the
// client's invoice numbering is not unique. These fixtures model that
// collision directly so the tests catch a regression back to keying on
// invoice_number instead of invoice_id.
const SHARED_INVOICE_NUMBER = "343653726836/1~3538"

const invoiceOne: InvoiceExtractPayload = {
  invoice_id: "invoice-1",
  invoice_number: SHARED_INVOICE_NUMBER,
  paired_assessment_number: "D7576879",
  vehicle_make: "SKODA",
  vehicle_model: "KAROQ SE TSI 115",
  vehicle_registration: "A30DRY",
  claim_number: "123456/1",
  policy_number: "103466899",
  field_sources: {},
  lines: [
    {
      id: "invoice-1-line-1",
      sequence_no: 1,
      line_item_type: "labour",
      raw_category: "Total Labour Amount",
      description: "Total Labour Amount",
      quantity: null,
      unit_price: null,
      line_total: "1910.00",
      is_section_total: true,
      item_kind: "unknown",
    },
  ],
}

const invoiceSeven: InvoiceExtractPayload = {
  invoice_id: "invoice-7",
  invoice_number: SHARED_INVOICE_NUMBER,
  paired_assessment_number: "D9911002",
  vehicle_make: null,
  vehicle_model: null,
  vehicle_registration: "JK21MNO",
  claim_number: "426953180/3",
  policy_number: "PH2",
  field_sources: {
    make: {
      document_id: "doc-assessment-7",
      label: "Filled from engineer assessment",
      value: "HYUNDAI",
    },
  },
  lines: [
    {
      id: "invoice-7-line-1",
      sequence_no: 1,
      line_item_type: "labour",
      raw_category: "Total Labour Amount",
      description: "Total Labour Amount",
      quantity: null,
      unit_price: null,
      line_total: "2509.20",
      is_section_total: true,
      item_kind: "unknown",
    },
  ],
}

const assessmentOne: AssessmentExtractPayload = {
  assessment_id: "assessment-1",
  assessment_number: "D7576879",
  vehicle_make: "SKODA",
  vehicle_model: "KAROQ SE TSI 115",
  vehicle_registration: "A30DRY",
  claim_number: "123456/1",
  policy_number: "103466899",
  paired_invoice_number: SHARED_INVOICE_NUMBER,
  pair_status: "paired",
  pair_confidence: 1,
  pair_reasons: ["registration exact match", "claim reference exact match"],
  lines: [
    {
      sequence_no: 1,
      line_item_type: "labour",
      raw_category: "LABOUR",
      description: "Front bumper replace",
      work_units: "14.0000",
      hours: "1.4000",
      unit_price: "80.00",
      line_total: "112.00",
      price_derived: true,
    },
  ],
}

const breakdownOne: SectionBreakdownPayload = {
  invoice_id: "invoice-1",
  invoice_number: SHARED_INVOICE_NUMBER,
  invoice_line_item_id: "invoice-1-line-1",
  line_item_type: "labour",
  raw_category: "Total Labour Amount",
  description: "Total Labour Amount",
  invoice_total: "1910.00",
  assessment_id: "assessment-1",
  assessment_total: "1910.00",
  matches: true,
  difference: "0.00",
  breakdown_source: "engineer assessment",
  rows: [
    {
      id: "op-1",
      category: "labour",
      raw_category: "LABOUR",
      description: "Front bumper replace",
      work_units: "14.0000",
      hours: "1.4000",
      unit_price_net: "80.00",
      total_net: "112.00",
    },
  ],
}

const breakdownSeven: SectionBreakdownPayload = {
  invoice_id: "invoice-7",
  invoice_number: SHARED_INVOICE_NUMBER,
  invoice_line_item_id: "invoice-7-line-1",
  line_item_type: "labour",
  raw_category: "Total Labour Amount",
  description: "Total Labour Amount",
  invoice_total: "2509.20",
  assessment_id: "assessment-7",
  assessment_total: "2509.20",
  matches: true,
  difference: "0.00",
  breakdown_source: "engineer assessment",
  rows: [
    {
      id: "op-7",
      category: "labour",
      raw_category: "LABOUR",
      description: "Rear bumper replace",
      work_units: "10.0000",
      hours: "1.0000",
      unit_price_net: "80.00",
      total_net: "800.00",
    },
  ],
}

const fixture: ClaimExtractsPayload = {
  invoice_extracts: [invoiceOne, invoiceSeven],
  assessment_extracts: [assessmentOne],
  section_breakdowns: [breakdownOne, breakdownSeven],
}

function renderStatic(node: ReturnType<typeof createElement>) {
  return renderToStaticMarkup(createElement(TooltipProvider, null, node))
}

function render(payload: ClaimExtractsPayload | null, loading = false, error: string | null = null) {
  return renderStatic(
    createElement(ExtractsSection, { extracts: payload, loading, error })
  )
}

describe("invoice and assessment extracts section", () => {
  it("renders both tables with their identity columns", () => {
    const html = render(fixture)
    expect(html).toContain("Invoice extracts and associated engineer assessment")
    expect(html).toContain("Engineer assessment extracts and invoice association")
    expect(html).toContain(SHARED_INVOICE_NUMBER)
    expect(html).toContain("D7576879")
    expect(html).toContain("SKODA")
    expect(html).toContain("A30DRY")
  })

  it("marks a gap-filled identity cell as coming from the assessment", () => {
    const html = render(fixture)
    expect(html).toContain("from assessment")
  })

  // Every row now starts collapsed. Auto-expansion existed only to reveal
  // the assessment split without a click; with the split off this screen
  // (§3.7) there is nothing left for it to reveal, so the rule was removed
  // rather than left running against nothing.
  it("starts every invoice row collapsed", () => {
    const itemised: InvoiceExtractPayload = {
      ...invoiceOne,
      invoice_id: "invoice-itemised",
      lines: [
        {
          id: "invoice-itemised-line-1",
          sequence_no: 1,
          line_item_type: "parts",
          raw_category: "PARTS",
          description: "Bonnet panel",
          quantity: "1",
          unit_price: "310.00",
          line_total: "310.00",
          is_section_total: false,
          item_kind: "part",
        },
      ],
    }
    const html = renderStatic(
      createElement(InvoiceExtractsTable, { invoices: [itemised] })
    )
    expect(html).not.toContain("Bonnet panel")
    expect(html).toContain("Expand lines for invoice")
  })

  it("keeps a manual collapse control on a row opened with expansion=all", () => {
    const html = renderStatic(
      createElement(InvoiceExtractsTable, {
        invoices: [invoiceOne],
        expansion: "all",
      })
    )
    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain("Collapse lines for invoice")
  })

  it("leaves assessment rows collapsed: a 120-operation report would bury the page", () => {
    const html = render(fixture)
    expect(html).toContain("Expand lines for engineer assessment D7576879")
  })

  it("shows a loading state and an error state", () => {
    const loadingHtml = render(null, true, null)
    expect(loadingHtml).toContain(
      "Loading invoice and engineer assessment extracts"
    )

    const errorHtml = render(null, false, "The API request failed.")
    expect(errorHtml).toContain("Extracts could not be loaded")
    expect(errorHtml).toContain("The API request failed.")
  })

  it("shows the empty state when there are no extracts at all", () => {
    const emptyFixture: ClaimExtractsPayload = {
      invoice_extracts: [],
      assessment_extracts: [],
      section_breakdowns: [],
    }
    const html = render(emptyFixture)
    expect(html).toContain(
      "No invoice or engineer assessment extracts are available for this claim yet."
    )
  })
})

describe("keying by invoice_id instead of the non-unique invoice_number", () => {
  it("keeps each shared-invoice-number invoice's own lines separate when expanded", () => {
    const html = renderStatic(
      createElement(InvoiceExtractsTable, {
        invoices: [invoiceOne, invoiceSeven],
        expansion: "all",
      })
    )
    // Both invoices print the same invoice_number, so anything keyed on that
    // rather than on invoice_id would collapse the two rows into one set of
    // lines -- and one association.
    expect(html).toContain("£1,910.00")
    expect(html).toContain("£2,509.20")
    expect(html).toContain("D7576879")
    expect(html).toContain("D9911002")
  })
})

describe("breakdown and operation rows render their own text", () => {
  it("renders a breakdown row by its description text", () => {
    const html = renderStatic(createElement(SectionBreakdownDetail, { breakdown: breakdownOne }))
    expect(html).toContain("Front bumper replace")
  })

  it("renders an assessment operation row by its description text", () => {
    const html = renderStatic(
      createElement(AssessmentLinesTable, { lines: assessmentOne.lines })
    )
    expect(html).toContain("Front bumper replace")
  })

  it("shows rows_total beside the assessment total when present", () => {
    const withRowsTotal: SectionBreakdownPayload = {
      ...breakdownOne,
      rows_total: "1910.00",
    }
    const html = renderStatic(createElement(SectionBreakdownDetail, { breakdown: withRowsTotal }))
    expect(html).toContain("rows total £1,910.00")
  })

  it("makes the section label a link to its paired assessment operations", () => {
    const html = renderStatic(
      createElement(InvoiceExtractsTable, {
        invoices: [invoiceOne],
        expansion: "all",
        linking: {
          extracts: fixture,
          state: {
            link: null,
            notice: null,
            focusedInvoiceId: null,
            scroll: null,
          },
          onSectionTotal: () => {},
          onAssessmentNumber: () => {},
          onInvoiceNumber: () => {},
          onShowAll: () => {},
          onBack: () => {},
          onRelease: () => {},
          onDismissNotice: () => {},
        },
      })
    )
    expect(html).toContain(
      'aria-label="Show the engineer assessment operations in Labour"'
    )
  })
})

// A reader has to be able to tell "the tool failed to line these up" from
// "the document does not say". `breakdown_available` is `bool(rows)` on the
// backend, so it reports only *that* there are no rows -- these three cases
// are separated by reading `assessment_id` and `assessment_total` too.
describe("the three empty-breakdown cases each say something different", () => {
  function renderBreakdown(breakdown: SectionBreakdownPayload) {
    return renderStatic(createElement(SectionBreakdownDetail, { breakdown }))
  }

  const unpaired: SectionBreakdownPayload = {
    ...breakdownOne,
    assessment_id: null,
    assessment_total: null,
    matches: null,
    difference: null,
    breakdown_available: false,
    rows_total: null,
    rows: [],
  }

  const unresolved: SectionBreakdownPayload = {
    ...breakdownOne,
    line_item_type: "unknown",
    raw_category: "Total Sundries",
    description: "Total Sundries",
    assessment_total: null,
    matches: null,
    difference: null,
    breakdown_available: false,
    rows_total: null,
    rows: [],
  }

  // Formats 1 and 7: the assessment prints a paint/materials total and no
  // paint-materials operations whatsoever. Nothing failed.
  const totalOnly: SectionBreakdownPayload = {
    ...breakdownOne,
    line_item_type: "paint_materials",
    raw_category: "Total Paint / Materials Costs",
    description: "Total Paint / Materials Costs",
    invoice_total: "396.00",
    assessment_total: "396.00",
    matches: true,
    difference: "0.00",
    breakdown_available: false,
    rows_total: null,
    rows: [],
  }

  it("says nothing is paired when the invoice has no assessment at all", () => {
    const html = renderBreakdown(unpaired)
    expect(html).toContain("No engineer assessment is paired to this invoice")
    expect(html).toContain(
      "Check the pairing on Document intelligence."
    )
  })

  it("says the section resolves to no assessment category", () => {
    const html = renderBreakdown(unresolved)
    expect(html).toContain("This section resolves to no engineer assessment category")
    expect(html).toContain("could not build a split")
  })

  it("says the assessment prints a total only, and that nothing failed", () => {
    const html = renderBreakdown(totalOnly)
    expect(html).toContain("The engineer assessment prints this section as a total only")
    expect(html).toContain(
      "The document does not itemise it — the extraction did not fail."
    )
  })

  it("gives each case its own wording", () => {
    const rendered = [unpaired, unresolved, totalOnly].map(renderBreakdown)
    for (const phrase of [
      "No engineer assessment is paired to this invoice",
      "This section resolves to no engineer assessment category",
      "The engineer assessment prints this section as a total only",
    ]) {
      expect(rendered.filter((html) => html.includes(phrase))).toHaveLength(1)
    }
  })

  it("offers no collapse control for a breakdown with nothing in it", () => {
    expect(renderBreakdown(unpaired)).not.toContain(
      "the engineer assessment breakdown for"
    )
  })
})

describe("difference_convention is explained in words, not as a formula", () => {
  it("says a positive difference means the repairer billed more", () => {
    const withConvention = {
      ...breakdownOne,
      difference_convention: "invoice_total - assessment_total",
    } as SectionBreakdownPayload
    const html = renderStatic(
      createElement(SectionBreakdownDetail, { breakdown: withConvention })
    )
    expect(html).toContain("invoice total - assessment total")
    expect(html).toContain(
      "a positive difference means the repairer billed more than the engineer assessed"
    )
  })

  it("stays quiet when the payload carries no convention", () => {
    const html = renderStatic(
      createElement(SectionBreakdownDetail, { breakdown: breakdownOne })
    )
    expect(html).not.toContain("a positive difference means")
  })
})

// The backend emits `assessment_total = None` for two different reasons: the
// invoice section resolves to no assessment section at all, or it resolves to
// one whose column the paired document simply left blank (all four of
// `parts_net` / `paint_net` / `extras_net` / `labour_net` are nullable). Under
// the old classification -- "paired and no total means unresolved" -- an
// invoice printing "Total Extras" beside an assessment with no extras section
// told the handler the tool had failed to match anything, when the document
// just carries no such figure.
describe("the fourth empty-breakdown case: resolvable, but the assessment prints no total", () => {
  const noSectionTotal: SectionBreakdownPayload = {
    ...breakdownOne,
    line_item_type: "extras",
    raw_category: "Total Extras",
    description: "Total Extras",
    invoice_total: "120.00",
    assessment_total: null,
    matches: null,
    difference: null,
    breakdown_available: false,
    rows_total: null,
    rows: [],
  }

  const unresolvable: SectionBreakdownPayload = {
    ...noSectionTotal,
    line_item_type: "unknown",
    raw_category: "Total Sundries",
    description: "Total Sundries",
  }

  it("does not call a blank assessment column a failure to match", () => {
    const html = renderStatic(
      createElement(SectionBreakdownDetail, { breakdown: noSectionTotal })
    )
    expect(html).toContain(
      "The paired engineer assessment prints no total for this section"
    )
    expect(html).toContain("the extraction did not fail")
    expect(html).not.toContain("This section resolves to no engineer assessment category")
  })

  it("still calls a genuinely unresolvable section unresolved", () => {
    const html = renderStatic(
      createElement(SectionBreakdownDetail, { breakdown: unresolvable })
    )
    expect(html).toContain("This section resolves to no engineer assessment category")
    expect(html).not.toContain(
      "The paired engineer assessment prints no total for this section"
    )
  })

  it("classifies on line_item_type, so every resolvable section reads the same", () => {
    for (const type of ["parts", "paint_materials", "extras", "labour"]) {
      const html = renderStatic(
        createElement(SectionBreakdownDetail, {
          breakdown: { ...noSectionTotal, line_item_type: type },
        })
      )
      expect(html).toContain(
        "The paired engineer assessment prints no total for this section"
      )
    }
  })
})

// The section's own payload still carries `section_breakdowns` -- the
// backend still emits them, and benchmark analysis will need them -- but
// nothing on Document Intelligence may read them. These guard the ways a
// breakdown used to leak onto the screen.
describe("no breakdown reaches the screen, whatever the payload carries", () => {
  it("shows no breakdown even when the payload is full of them", () => {
    const html = render(fixture)
    expect(html).not.toContain("ssessment breakdown")
    expect(html).not.toContain("No engineer assessment is paired to this invoice")
    expect(html).not.toContain("Rolled-up total")
  })

  it("opens nothing under expansion=\"none\"", () => {
    const html = renderStatic(
      createElement(InvoiceExtractsTable, {
        invoices: [invoiceOne],
        expansion: "none",
      })
    )
    expect(html).not.toContain("ssessment breakdown")
    expect(html).toContain("Expand lines for invoice")
  })

  it("opens nothing under the default expansion either", () => {
    const html = renderStatic(
      createElement(InvoiceExtractsTable, { invoices: [invoiceOne] })
    )
    expect(html).not.toContain("ssessment breakdown")
    expect(html).toContain("Expand lines for invoice")
  })
})

describe("the difference convention is not asserted where there is no difference", () => {
  const convention = "invoice_total - assessment_total"

  it("stays quiet when nothing is paired to the invoice", () => {
    const html = renderStatic(
      createElement(SectionBreakdownDetail, {
        breakdown: {
          ...breakdownOne,
          assessment_id: null,
          assessment_total: null,
          matches: null,
          difference: null,
          breakdown_available: false,
          rows: [],
          difference_convention: convention,
        } as SectionBreakdownPayload,
      })
    )
    expect(html).toContain("No engineer assessment is paired to this invoice")
    expect(html).not.toContain("a positive difference means")
  })

  it("stays quiet when the section resolves to nothing", () => {
    const html = renderStatic(
      createElement(SectionBreakdownDetail, {
        breakdown: {
          ...breakdownOne,
          line_item_type: "unknown",
          assessment_total: null,
          matches: null,
          difference: null,
          breakdown_available: false,
          rows: [],
          difference_convention: convention,
        } as SectionBreakdownPayload,
      })
    )
    expect(html).toContain("This section resolves to no engineer assessment category")
    expect(html).not.toContain("a positive difference means")
  })

  it("still explains the sign when there is a difference to explain", () => {
    const html = renderStatic(
      createElement(SectionBreakdownDetail, {
        breakdown: {
          ...breakdownOne,
          difference: "120.00",
          matches: false,
          difference_convention: convention,
        } as SectionBreakdownPayload,
      })
    )
    expect(html).toContain(
      "a positive difference means the repairer billed more than the engineer assessed"
    )
  })
})

// `pair_key_verdicts` was typed `string[]` while the backend emits one object
// per key. Spreading those objects into a joined string prints
// "[object Object]" the moment anything wires the field in.
describe("per-key pairing verdicts render their own sentences", () => {
  it("never prints [object Object] for a verdict", () => {
    const withVerdicts: AssessmentExtractPayload = {
      ...assessmentOne,
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
          key: "policy_number",
          label: "policy number",
          state: "placeholder",
          compared: false,
          absent_on: "invoice",
          placeholder_on: "assessment",
          assessment_value: "PH",
          invoice_value: null,
          text: "policy number is a placeholder on the assessment (PH)",
        },
      ],
    }
    const html = renderStatic(
      createElement(AssessmentExtractsTable, { assessments: [withVerdicts] })
    )
    expect(html).not.toContain("[object Object]")
    expect(html).toContain(
      "policy number is a placeholder on the assessment (PH)"
    )
  })
})

// ---------------------------------------------------------------------------
// 17 Sep walkthrough, §3: headings, association columns, and each section
// showing only what its own document contains.
// ---------------------------------------------------------------------------

describe("the two tables are headed and associated the way the client asked", () => {
  it("heads the invoice table with its associated engineer assessment", () => {
    expect(render(fixture)).toContain(
      "Invoice extracts and associated engineer assessment"
    )
  })

  it("heads the assessment table with its invoice association", () => {
    expect(render(fixture)).toContain(
      "Engineer assessment extracts and invoice association"
    )
  })

  it("puts the associated assessment number straight after the invoice number", () => {
    const html = renderStatic(
      createElement(InvoiceExtractsTable, { invoices: [invoiceOne] })
    )
    expect(html).toContain("Associated assessment number")
    expect(html.indexOf("Invoice number")).toBeLessThan(
      html.indexOf("Associated assessment number")
    )
    // The number itself, not just the heading.
    expect(html).toContain("D7576879")
  })

  it("puts the associated invoice number straight after the assessment number", () => {
    const html = renderStatic(
      createElement(AssessmentExtractsTable, { assessments: [assessmentOne] })
    )
    expect(html).toContain("Associated invoice number")
    expect(html.indexOf("Assessment number")).toBeLessThan(
      html.indexOf("Associated invoice number")
    )
  })

  // "A blank association must render as a visible 'not paired' state, not an
  // empty cell." The em dash used for every other identity column means "the
  // document did not print it"; an absent association is a different fact
  // about a different document and must not borrow that wording.
  it("says in words that an invoice has no associated assessment", () => {
    const html = renderStatic(
      createElement(InvoiceExtractsTable, {
        invoices: [{ ...invoiceOne, paired_assessment_number: null }],
      })
    )
    expect(html).toContain("Not paired")
  })

  it("says in words that an assessment has no associated invoice", () => {
    const html = renderStatic(
      createElement(AssessmentExtractsTable, {
        assessments: [
          {
            ...assessmentOne,
            pair_status: "unpaired" as const,
            paired_invoice_number: null,
          },
        ],
      })
    )
    expect(html).toContain("Not paired")
  })
})

// §3.7: "If the invoice is not talking about parts, you won't show the part
// line items there. You would show those parts in the assessment section,
// which is below." The split is not cancelled -- it moves to benchmark
// analysis -- but it must not render inside the invoice extracts table.
describe("the invoice table shows only what the invoice itself prints", () => {
  it("renders no assessment breakdown under a rolled-up total, even fully expanded", () => {
    const html = renderStatic(
      createElement(InvoiceExtractsTable, {
        invoices: [invoiceOne],
        expansion: "all",
      })
    )
    // The invoice's own rolled-up line is still there, still badged.
    expect(html).toContain("Total Labour Amount")
    expect(html).toContain("Rolled-up total")
    // The assessment's rows behind it are not.
    expect(html).not.toContain("ssessment breakdown")
    expect(html).not.toContain("Front bumper replace")
    expect(html).not.toContain("Total Labour £1,910.00 billed")
  })

  it("opens no invoice row by itself: there is no longer a split to reveal", () => {
    const html = render(fixture)
    expect(html).not.toContain("ssessment breakdown")
    expect(html).not.toContain("Collapse lines for invoice")
    expect(html.match(/Expand lines for invoice/g) ?? []).toHaveLength(2)
  })
})

// §3.1: "call it engineer assessment everywhere". The split was parked
// unmounted on 17 Sep before the sweep reached it; it is mounted on
// benchmark analysis now, so it has to speak the same language as the rest.
describe("the breakdown calls it an engineer assessment", () => {
  it("heads the split Engineer assessment breakdown", () => {
    const html = renderStatic(
      createElement(SectionBreakdownDetail, { breakdown: breakdownOne })
    )
    expect(html).toContain("Engineer assessment breakdown")
    expect(html).toContain("Collapse the engineer assessment breakdown for")
  })

  it("names the engineer assessment in its match badge and summary", () => {
    expect(
      renderStatic(createElement(SectionBreakdownDetail, { breakdown: breakdownOne }))
    ).toContain("Matches engineer assessment")
    expect(
      renderStatic(
        createElement(SectionBreakdownDetail, {
          breakdown: { ...breakdownOne, matches: false, difference: "10.00" },
        })
      )
    ).toContain("Does not match engineer assessment")
    const notCaptured = renderStatic(
      createElement(SectionBreakdownDetail, {
        breakdown: {
          ...breakdownOne,
          assessment_total: null,
          matches: null,
          difference: null,
        },
      })
    )
    expect(notCaptured).toContain("Not captured on the engineer assessment")
    expect(notCaptured).toContain("not captured on the engineer assessment")
  })

  it("never says a bare 'assessment' where it means the document", () => {
    for (const breakdown of [
      breakdownOne,
      { ...breakdownOne, assessment_id: null, rows: [], breakdown_available: false },
      { ...breakdownOne, line_item_type: "unknown", rows: [], breakdown_available: false },
      { ...breakdownOne, assessment_total: null, rows: [], breakdown_available: false },
      { ...breakdownOne, rows: [], breakdown_available: false },
    ] as SectionBreakdownPayload[]) {
      const text = renderStatic(
        createElement(SectionBreakdownDetail, { breakdown })
      ).replace(/<[^>]+>/g, " ")
      // "assessment" is always preceded by "engineer" -- "assessed" is a
      // different word and allowed.
      expect(text).not.toMatch(/(?<!engineer )\bassessment\b/i)
    }
  })
})
