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
    expect(html).toContain("Invoice extracts")
    expect(html).toContain("Assessment extracts")
    expect(html).toContain(SHARED_INVOICE_NUMBER)
    expect(html).toContain("D7576879")
    expect(html).toContain("SKODA")
    expect(html).toContain("A30DRY")
  })

  it("marks a gap-filled identity cell as coming from the assessment", () => {
    const html = render(fixture)
    expect(html).toContain("from assessment")
  })

  // The client's whole ask: "total parts in invoice = 110 means from the
  // engineer estimate we shud show what all parts line items r taken exactly
  // to get tht total parts cost". Both fixture invoices roll their costs up
  // into a section total, so both open themselves and show the assessment
  // rows behind the total -- with no click anywhere. `renderToStaticMarkup`
  // has no pointer, so anything in this markup was reached without one.
  it("shows the split for a rolled-up total with no interaction at all", () => {
    const html = render(fixture)
    expect(html).toContain("Rolled-up total")
    expect(html).toContain("Assessment breakdown")
    expect(html).toContain("Total Labour £1,910.00 billed")
    expect(html).toContain("Front bumper replace")
    expect(html).toContain("Rear bumper replace")
  })

  it("leaves a fully itemised invoice collapsed: it has no split to show", () => {
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
      createElement(InvoiceExtractsTable, {
        invoices: [itemised],
        breakdowns: [],
      })
    )
    expect(html).not.toContain("Bonnet panel")
  })

  it("leaves a rolled-up invoice collapsed once it runs past the auto-expand line limit", () => {
    // 41 lines is one past AUTO_EXPAND_LINE_LIMIT. Opening a 300-line
    // invoice would bury the very breakdown it was opened for.
    const long: InvoiceExtractPayload = {
      ...invoiceOne,
      invoice_id: "invoice-long",
      lines: [
        ...invoiceOne.lines,
        ...Array.from({ length: 40 }, (_unused, index) => ({
          id: `invoice-long-line-${index + 2}`,
          sequence_no: index + 2,
          line_item_type: "parts",
          raw_category: "PARTS",
          description: `Filler part ${index + 2}`,
          quantity: "1",
          unit_price: "10.00",
          line_total: "10.00",
          is_section_total: false,
          item_kind: "part",
        })),
      ],
    }
    const html = renderStatic(
      createElement(InvoiceExtractsTable, {
        invoices: [long],
        breakdowns: [{ ...breakdownOne, invoice_id: "invoice-long" }],
      })
    )
    expect(html).not.toContain("Assessment breakdown")
    expect(html).not.toContain("Filler part 2")
  })

  it("keeps a manual collapse control on every auto-expanded disclosure", () => {
    const html = render(fixture)
    // Auto-expanding must not take the control away: an opened invoice row
    // and the breakdown inside it both still advertise aria-expanded="true"
    // on a button that closes them again.
    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain("Collapse lines for invoice")
    expect(html).toContain("Collapse the assessment breakdown for")
  })

  it("leaves assessment rows collapsed: the split already lives on the invoice side", () => {
    const html = render(fixture)
    // assessmentOne's only operation is already visible inside the invoice's
    // breakdown; its own disclosure stays shut so a 120-operation report
    // does not push everything else off the page.
    expect(html).toContain("Expand lines for assessment D7576879")
  })

  it("shows a loading state and an error state", () => {
    const loadingHtml = render(null, true, null)
    expect(loadingHtml).toContain("Loading invoice and assessment extracts")

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
      "No invoice or assessment extracts are available for this claim yet."
    )
  })
})

describe("keying by invoice_id instead of the non-unique invoice_number", () => {
  it("keeps each shared-invoice-number invoice's own breakdown total separate when expanded", () => {
    const html = renderStatic(
      createElement(InvoiceExtractsTable, {
        invoices: [invoiceOne, invoiceSeven],
        breakdowns: [breakdownOne, breakdownSeven],
        expansion: "all",
      })
    )
    // Both invoices share one invoice_number, so if the breakdown lookup
    // keyed on invoice_number instead of invoice_id, both rows would show
    // the same total. They must not.
    expect(html).toContain("Rolled-up total")
    expect(html).toContain("Total Labour £1,910.00 billed")
    expect(html).toContain("Total Labour £2,509.20 billed")
    expect(html).toContain("Front bumper replace")
    expect(html).toContain("Rear bumper replace")
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
    expect(html).toContain("No assessment is paired to this invoice")
    expect(html).toContain(
      "Check the pairing verdict on the assessment extracts table below."
    )
  })

  it("says the section resolves to no assessment category", () => {
    const html = renderBreakdown(unresolved)
    expect(html).toContain("This section resolves to no assessment category")
    expect(html).toContain("could not build a split")
  })

  it("says the assessment prints a total only, and that nothing failed", () => {
    const html = renderBreakdown(totalOnly)
    expect(html).toContain("The assessment prints this section as a total only")
    expect(html).toContain(
      "The document does not itemise it — the extraction did not fail."
    )
  })

  it("gives each case its own wording", () => {
    const rendered = [unpaired, unresolved, totalOnly].map(renderBreakdown)
    for (const phrase of [
      "No assessment is paired to this invoice",
      "This section resolves to no assessment category",
      "The assessment prints this section as a total only",
    ]) {
      expect(rendered.filter((html) => html.includes(phrase))).toHaveLength(1)
    }
  })

  it("offers no collapse control for a breakdown with nothing in it", () => {
    expect(renderBreakdown(unpaired)).not.toContain(
      "the assessment breakdown for"
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
      "The paired assessment prints no total for this section"
    )
    expect(html).toContain("the extraction did not fail")
    expect(html).not.toContain("This section resolves to no assessment category")
  })

  it("still calls a genuinely unresolvable section unresolved", () => {
    const html = renderStatic(
      createElement(SectionBreakdownDetail, { breakdown: unresolvable })
    )
    expect(html).toContain("This section resolves to no assessment category")
    expect(html).not.toContain(
      "The paired assessment prints no total for this section"
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
        "The paired assessment prints no total for this section"
      )
    }
  })
})

// `get_claim_extracts` emits a breakdown for *every* `is_section_total` line
// unconditionally, paired or not. Auto-expanding on "a breakdown exists" meant
// that uploading invoices before any estimate blew every rolled-up invoice
// open onto four "No assessment is paired to this invoice" boxes -- the
// opposite of putting the split in front of the reader. The same
// `ExtractsSection` renders on Review findings, so this covers both screens.
describe("auto-expansion needs a breakdown that actually resolves", () => {
  const unpairedBreakdown: SectionBreakdownPayload = {
    ...breakdownOne,
    assessment_id: null,
    assessment_total: null,
    matches: null,
    difference: null,
    breakdown_available: false,
    rows_total: null,
    rows: [],
  }

  it("leaves a rolled-up invoice collapsed when nothing is paired to it", () => {
    const html = renderStatic(
      createElement(InvoiceExtractsTable, {
        invoices: [invoiceOne],
        breakdowns: [unpairedBreakdown],
      })
    )
    expect(html).not.toContain("Assessment breakdown")
    expect(html).not.toContain("No assessment is paired to this invoice")
    expect(html).toContain("Expand lines for invoice")
  })

  it("does not dump a whole claim of unpaired invoices open", () => {
    const payload: ClaimExtractsPayload = {
      invoice_extracts: [invoiceOne, invoiceSeven],
      assessment_extracts: [],
      section_breakdowns: [
        { ...unpairedBreakdown, invoice_id: "invoice-1" },
        {
          ...unpairedBreakdown,
          invoice_id: "invoice-7",
          invoice_line_item_id: "invoice-7-line-1",
        },
      ],
    }
    const html = render(payload)
    expect(html).not.toContain("Assessment breakdown")
    // Every invoice row still advertises "Expand", never "Collapse": not one
    // of them was pre-opened. (The card's own Hide/Show trigger is a
    // different control and is open by design.)
    expect(html).not.toContain("Collapse lines for invoice")
    expect(html.match(/Expand lines for invoice/g) ?? []).toHaveLength(2)
  })

  it("still opens an invoice whose breakdown carries rows", () => {
    const html = renderStatic(
      createElement(InvoiceExtractsTable, {
        invoices: [invoiceOne],
        breakdowns: [breakdownOne],
      })
    )
    expect(html).toContain("Assessment breakdown")
    expect(html).toContain("Front bumper replace")
  })

  // The old prop was `defaultExpanded?: boolean`, under which `undefined`
  // meant "apply the auto-expand rule" and `false` meant "open nothing" --
  // two spellings of "not pre-expanded" that behaved differently, with
  // nothing on the type to say so. The three named states each mean one
  // thing.
  it("opens nothing at all under expansion=\"none\", auto-expand rule or not", () => {
    const html = renderStatic(
      createElement(InvoiceExtractsTable, {
        invoices: [invoiceOne],
        breakdowns: [breakdownOne],
        expansion: "none",
      })
    )
    expect(html).not.toContain("Assessment breakdown")
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
    expect(html).toContain("No assessment is paired to this invoice")
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
    expect(html).toContain("This section resolves to no assessment category")
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
