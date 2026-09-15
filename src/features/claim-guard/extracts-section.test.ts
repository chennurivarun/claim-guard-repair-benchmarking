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

  it("collapses row-level disclosures by default so the section stays short", () => {
    const html = render(fixture)
    // The rolled-up-total badge and line-item content only exist inside
    // the (collapsed) detail rows.
    expect(html).not.toContain("Rolled-up total")
    expect(html).not.toContain("Front bumper replace")
    expect(html).not.toContain("Rear bumper replace")
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
        defaultExpanded: true,
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

  it("renders 'No breakdown rows on the assessment' when breakdown_available is false", () => {
    const unavailable: SectionBreakdownPayload = {
      ...breakdownOne,
      breakdown_available: false,
      rows: [],
    }
    const html = renderStatic(createElement(SectionBreakdownDetail, { breakdown: unavailable }))
    expect(html).toContain("No breakdown rows on the assessment")
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
