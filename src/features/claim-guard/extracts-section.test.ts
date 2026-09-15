import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { TooltipProvider } from "@/components/ui/tooltip"
import type { ClaimExtractsPayload } from "@/lib/api"
import { ExtractsSection } from "./extracts-section"

const fixture: ClaimExtractsPayload = {
  invoice_extracts: [
    {
      invoice_number: "123456/1-INV",
      vehicle_make: "SKODA",
      vehicle_model: "KAROQ SE TSI 115",
      vehicle_registration: "A30DRY",
      claim_number: "123456/1",
      policy_number: "103466899",
      field_sources: {},
      lines: [
        {
          sequence_no: 1,
          line_item_type: "labour",
          raw_category: "Total Labour Amount",
          description: "Total Labour Amount",
          quantity: null,
          unit_price: null,
          line_total: "2008.00",
          is_section_total: true,
          item_kind: "unknown",
        },
      ],
    },
    {
      invoice_number: "426953180/3-INV",
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
          sequence_no: 1,
          line_item_type: "parts",
          raw_category: "Parts",
          description: "Front bumper",
          quantity: "1.0000",
          unit_price: "120.00",
          line_total: "120.00",
          is_section_total: false,
          item_kind: "part",
        },
      ],
    },
  ],
  assessment_extracts: [
    {
      assessment_number: "D7576879",
      vehicle_make: "SKODA",
      vehicle_model: "KAROQ SE TSI 115",
      vehicle_registration: "A30DRY",
      claim_number: "123456/1",
      policy_number: "103466899",
      paired_invoice_number: "123456/1-INV",
      pair_status: "paired",
      pair_confidence: 1,
      pair_reasons: ["registration exact match", "claim reference exact match"],
      lines: [
        {
          sequence_no: 1,
          line_item_type: "labour",
          raw_category: "LABOUR",
          description: "Front bumper R&R",
          work_units: "14.0000",
          hours: "1.4000",
          unit_price: "80.00",
          line_total: "112.00",
          price_derived: true,
        },
      ],
    },
  ],
  section_breakdowns: [
    {
      invoice_number: "123456/1-INV",
      invoice_line_item_id: "line-1",
      line_item_type: "labour",
      raw_category: "Total Labour Amount",
      description: "Total Labour Amount",
      invoice_total: "2008.00",
      assessment_id: "assessment-1",
      assessment_total: "1112.00",
      matches: false,
      difference: "896.00",
      breakdown_source: "engineer assessment",
      rows: [
        {
          id: "op-1",
          category: "labour",
          raw_category: "LABOUR",
          description: "Front bumper R&R",
          work_units: "14.0000",
          hours: "1.4000",
          unit_price_net: "80.00",
          total_net: "112.00",
        },
      ],
    },
  ],
}

function render(payload: ClaimExtractsPayload | null, loading = false, error: string | null = null) {
  return renderToStaticMarkup(
    createElement(
      TooltipProvider,
      null,
      createElement(ExtractsSection, { extracts: payload, loading, error })
    )
  )
}

describe("invoice and assessment extracts section", () => {
  it("renders both tables with their identity columns", () => {
    const html = render(fixture)
    expect(html).toContain("Invoice extracts")
    expect(html).toContain("Assessment extracts")
    expect(html).toContain("123456/1-INV")
    expect(html).toContain("D7576879")
    expect(html).toContain("SKODA")
    expect(html).toContain("A30DRY")
  })

  it("marks a rolled-up section total row with a badge", () => {
    const html = render(fixture)
    expect(html).toContain("Rolled-up total")
  })

  it("marks a gap-filled identity cell as coming from the assessment", () => {
    const html = render(fixture)
    expect(html).toContain("from assessment")
  })

  it("shows the section breakdown summary line under the rolled-up total", () => {
    const html = render(fixture)
    expect(html).toContain(
      "Total Labour £2,008.00 billed · £1,112.00 assessed · £896.00 over"
    )
  })

  it("shows a loading state and an error state", () => {
    const loadingHtml = render(null, true, null)
    expect(loadingHtml).toContain("Loading invoice and assessment extracts")

    const errorHtml = render(null, false, "The API request failed.")
    expect(errorHtml).toContain("Extracts could not be loaded")
    expect(errorHtml).toContain("The API request failed.")
  })
})
