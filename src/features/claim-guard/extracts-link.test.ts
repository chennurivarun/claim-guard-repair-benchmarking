import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { TooltipProvider } from "@/components/ui/tooltip"
import type {
  AssessmentExtractLine,
  AssessmentExtractPayload,
  ClaimExtractsPayload,
  InvoiceExtractLine,
  InvoiceExtractPayload,
  SectionBreakdownPayload,
  SectionBreakdownRow,
} from "@/lib/api"
import {
  assessmentPartner,
  backToInvoice,
  filterSectionOperations,
  followAssessmentNumber,
  followInvoiceNumber,
  followSectionTotal,
  invoicePartner,
  linkRowIds,
  NO_LINK,
  releaseLink,
  showAllOperations,
  type ExtractsLinkState,
} from "./extracts-link"
import {
  AssessmentExtractsTable,
  InvoiceExtractsTable,
  type ExtractsLinking,
} from "./extracts-section"

// The client's screenshot: format 1's invoice prints no invoice number, and
// its engineer assessment is paired to it all the same.
const INVOICE_NUMBER = "343653726836/1~3538"

function invoiceLine(
  id: string,
  sequence: number,
  type: string,
  description: string,
  total: string,
  isSectionTotal = true
): InvoiceExtractLine {
  return {
    id,
    sequence_no: sequence,
    line_item_type: type,
    raw_category: description,
    description,
    quantity: null,
    unit_price: null,
    line_total: total,
    is_section_total: isSectionTotal,
    item_kind: "unknown",
  }
}

function operation(
  sequence: number,
  type: string,
  description: string,
  total: string
): AssessmentExtractLine {
  return {
    sequence_no: sequence,
    line_item_type: type,
    raw_category: type.toUpperCase(),
    description,
    work_units: null,
    hours: null,
    unit_price: null,
    line_total: total,
    price_derived: null,
  }
}

function row(id: string, line: AssessmentExtractLine): SectionBreakdownRow {
  return {
    id,
    category: line.line_item_type ?? "unknown",
    raw_category: line.raw_category,
    description: line.description,
    work_units: null,
    hours: null,
    unit_price_net: null,
    total_net: line.line_total,
  }
}

const partOne = operation(1, "parts", "Bumper cover", "300.00")
const partTwo = operation(2, "parts", "Grille", "100.00")
const partThree = operation(3, "parts", "Clip set", "48.91")
const labourOne = operation(4, "labour", "Bumper remove and refit", "120.00")
const labourTwo = operation(5, "labour", "Grille remove and refit", "40.00")
const paintOne = operation(6, "paint", "Bumper paint", "210.00")

const invoiceA: InvoiceExtractPayload = {
  invoice_id: "invoice-a",
  invoice_number: INVOICE_NUMBER,
  paired_assessment_number: "D100",
  vehicle_make: null,
  vehicle_model: null,
  vehicle_registration: null,
  claim_number: null,
  policy_number: null,
  field_sources: {},
  lines: [
    invoiceLine("a-parts", 1, "parts", "Total Parts", "448.91"),
    invoiceLine("a-labour", 2, "labour", "Total Labour", "370.00"),
    invoiceLine("a-paint", 3, "paint_materials", "Total Paint & Materials", "40.00"),
    invoiceLine("a-extra", 4, "unknown", "Additional charges", "15.00"),
  ],
}

const assessmentA: AssessmentExtractPayload = {
  assessment_id: "assessment-a",
  assessment_number: "D100",
  vehicle_make: null,
  vehicle_model: null,
  vehicle_registration: null,
  claim_number: null,
  policy_number: null,
  paired_invoice_number: INVOICE_NUMBER,
  pair_status: "paired",
  pair_confidence: 1,
  pair_reasons: [],
  lines: [partOne, partTwo, partThree, labourOne, labourTwo, paintOne],
}

// A second paired assessment carrying parts of its own: the filter must
// never reach into it.
const otherPart = operation(1, "parts", "Wing mirror glass", "90.00")
const invoiceB: InvoiceExtractPayload = {
  ...invoiceA,
  invoice_id: "invoice-b",
  invoice_number: null,
  paired_assessment_number: "D200",
  lines: [invoiceLine("b-parts", 1, "parts", "Total Parts", "90.00")],
}
const assessmentB: AssessmentExtractPayload = {
  ...assessmentA,
  assessment_id: "assessment-b",
  assessment_number: "D200",
  paired_invoice_number: null,
  lines: [otherPart],
}

const invoiceUnpaired: InvoiceExtractPayload = {
  ...invoiceA,
  invoice_id: "invoice-u",
  invoice_number: "INV-U",
  paired_assessment_number: null,
  lines: [invoiceLine("u-parts", 1, "parts", "Total Parts", "12.00")],
}

function breakdown(
  invoice: InvoiceExtractPayload,
  lineId: string,
  assessmentId: string | null,
  rows: SectionBreakdownRow[],
  assessmentTotal: string | null
): SectionBreakdownPayload {
  const line = invoice.lines.find((candidate) => candidate.id === lineId)!
  return {
    invoice_id: invoice.invoice_id,
    invoice_number: invoice.invoice_number,
    invoice_line_item_id: lineId,
    line_item_type: line.line_item_type ?? "unknown",
    raw_category: line.raw_category,
    description: line.description,
    invoice_total: line.line_total,
    assessment_id: assessmentId,
    assessment_total: assessmentTotal,
    matches: null,
    difference: null,
    breakdown_source: "engineer assessment",
    breakdown_available: rows.length > 0,
    rows,
  }
}

const partsBreakdown = breakdown(
  invoiceA,
  "a-parts",
  "assessment-a",
  [row("op-1", partOne), row("op-2", partTwo), row("op-3", partThree)],
  "448.91"
)
// The backend's `_section_categories("labour")` is labour + paint, so the
// rows it publishes for Total Labour already carry both codes.
const labourBreakdown = breakdown(
  invoiceA,
  "a-labour",
  "assessment-a",
  [row("op-4", labourOne), row("op-5", labourTwo), row("op-6", paintOne)],
  "370.00"
)
const paintMaterialsBreakdown = breakdown(
  invoiceA,
  "a-paint",
  "assessment-a",
  [],
  "40.00"
)
const unresolvedBreakdown = breakdown(invoiceA, "a-extra", "assessment-a", [], null)
const partsBreakdownB = breakdown(
  invoiceB,
  "b-parts",
  "assessment-b",
  [row("op-b1", otherPart)],
  "90.00"
)
const unpairedBreakdown = breakdown(invoiceUnpaired, "u-parts", null, [], null)

const extracts: ClaimExtractsPayload = {
  invoice_extracts: [invoiceA, invoiceB, invoiceUnpaired],
  assessment_extracts: [assessmentA, assessmentB],
  section_breakdowns: [
    partsBreakdown,
    labourBreakdown,
    paintMaterialsBreakdown,
    unresolvedBreakdown,
    partsBreakdownB,
    unpairedBreakdown,
  ],
}

function linking(state: ExtractsLinkState, payload = extracts): ExtractsLinking {
  const noop = () => {}
  return {
    extracts: payload,
    state,
    onSectionTotal: noop,
    onAssessmentNumber: noop,
    onInvoiceNumber: noop,
    onShowAll: noop,
    onBack: noop,
    onRelease: noop,
    onDismissNotice: noop,
  }
}

function text(node: ReturnType<typeof createElement>) {
  return renderToStaticMarkup(createElement(TooltipProvider, null, node))
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&#x27;/g, "'")
    .replace(/\s+/g, " ")
}

function assessmentTable(state: ExtractsLinkState, payload = extracts) {
  return text(
    createElement(AssessmentExtractsTable, {
      assessments: payload.assessment_extracts,
      linking: linking(state, payload),
    })
  )
}

function invoiceTable(state: ExtractsLinkState, payload = extracts) {
  return text(
    createElement(InvoiceExtractsTable, {
      invoices: payload.invoice_extracts,
      expansion: "all",
      linking: linking(state, payload),
    })
  )
}

describe("clicking a rolled-up section total", () => {
  it("jumps to that invoice's own engineer assessment, filtered to the section", () => {
    const state = followSectionTotal(NO_LINK, extracts, "invoice-a", "a-parts")
    expect(state.link).toEqual({
      assessmentId: "assessment-a",
      invoiceId: "invoice-a",
      invoiceLineId: "a-parts",
      breakdown: partsBreakdown,
    })
    expect(state.notice).toBeNull()
    expect(state.scroll?.elementIds).toEqual([
      linkRowIds.assessment("assessment-a"),
    ])
    expect(
      filterSectionOperations(assessmentA.lines, partsBreakdown).map(
        (line) => line.description
      )
    ).toEqual(["Bumper cover", "Grille", "Clip set"])
  })

  it("shows exactly that section's operations for exactly that engineer assessment", () => {
    const html = assessmentTable(
      followSectionTotal(NO_LINK, extracts, "invoice-a", "a-parts")
    )
    for (const part of ["Bumper cover", "Grille", "Clip set"]) {
      expect(html).toContain(part)
    }
    // Not the labour or paintwork on the same engineer assessment...
    expect(html).not.toContain("Bumper remove and refit")
    expect(html).not.toContain("Bumper paint")
    // ...and not the parts on another one.
    expect(html).not.toContain("Wing mirror glass")
  })

  it("includes paintwork behind Total Labour", () => {
    const state = followSectionTotal(NO_LINK, extracts, "invoice-a", "a-labour")
    expect(
      filterSectionOperations(assessmentA.lines, labourBreakdown).map(
        (line) => line.description
      )
    ).toEqual(["Bumper remove and refit", "Grille remove and refit", "Bumper paint"])
    const html = assessmentTable(state)
    expect(html).toContain("Bumper paint")
    expect(html).not.toContain("Bumper cover")
    expect(html).toContain(
      "Showing the 3 labour and paintwork operations behind Total Labour £370.00 on invoice 343653726836/1~3538"
    )
  })
})

describe("the filtered engineer assessment says what it is filtered to", () => {
  const filtered = followSectionTotal(NO_LINK, extracts, "invoice-a", "a-parts")

  it("names the count, the section, the amount and the invoice", () => {
    expect(assessmentTable(filtered)).toContain(
      "Showing the 3 parts behind Total Parts £448.91 on invoice 343653726836/1~3538"
    )
  })

  it("offers to show every operation and to go back up", () => {
    const html = assessmentTable(filtered)
    expect(html).toContain("Show all 6 operations")
    expect(html).toContain("Back to Total Parts on invoice 343653726836/1~3538")
  })

  it("show all keeps the same engineer assessment open, unfiltered", () => {
    const state = showAllOperations(filtered)
    expect(state.link).toEqual({ ...filtered.link, breakdown: null })
    expect(state.scroll?.elementIds).toEqual([
      linkRowIds.assessment("assessment-a"),
    ])
    const html = assessmentTable(state)
    expect(html).not.toContain("Showing the 3 parts")
    for (const description of [
      "Bumper cover",
      "Bumper remove and refit",
      "Bumper paint",
    ]) {
      expect(html).toContain(description)
    }
  })

  it("back returns to the invoice line the reader clicked, then its row", () => {
    const state = backToInvoice(filtered)
    expect(state.focusedInvoiceId).toBe("invoice-a")
    expect(state.scroll?.elementIds).toEqual([
      linkRowIds.invoiceLine("a-parts"),
      linkRowIds.invoice("invoice-a"),
    ])
  })

  it("a repeat click scrolls again", () => {
    const again = followSectionTotal(filtered, extracts, "invoice-a", "a-parts")
    expect(again.scroll?.seq).not.toBe(filtered.scroll?.seq)
  })

  it("collapsing the linked row drops the filter", () => {
    expect(releaseLink(filtered).link).toBeNull()
  })
})

describe("a section that cannot be followed says so where the reader clicked", () => {
  it("does not jump for an unpaired invoice", () => {
    const state = followSectionTotal(NO_LINK, extracts, "invoice-u", "u-parts")
    expect(state.link).toBeNull()
    expect(state.scroll).toBeNull()
    expect(state.notice).toEqual({ invoiceLineId: "u-parts", gap: "unpaired" })
    expect(invoiceTable(state)).toContain(
      "No engineer assessment is paired to this invoice"
    )
  })

  it("does not jump for a section that resolves to no category", () => {
    const state = followSectionTotal(NO_LINK, extracts, "invoice-a", "a-extra")
    expect(state.link).toBeNull()
    expect(state.scroll).toBeNull()
    expect(invoiceTable(state)).toContain(
      "This section resolves to no engineer assessment category"
    )
  })

  it("does not jump for a section the engineer assessment prints as a total only", () => {
    const state = followSectionTotal(NO_LINK, extracts, "invoice-a", "a-paint")
    expect(state.link).toBeNull()
    expect(state.scroll).toBeNull()
    expect(invoiceTable(state)).toContain(
      "The engineer assessment prints this section as a total only"
    )
  })

  it("does not jump for a section the engineer assessment leaves blank", () => {
    const blank = {
      ...extracts,
      section_breakdowns: [{ ...paintMaterialsBreakdown, assessment_total: null }],
    }
    const state = followSectionTotal(NO_LINK, blank, "invoice-a", "a-paint")
    expect(state.link).toBeNull()
    expect(invoiceTable(state, blank)).toContain(
      "The paired engineer assessment prints no total for this section"
    )
  })

  it("never jumps to an engineer assessment this screen does not show", () => {
    // A scoped screen: the invoice is in this source, its engineer
    // assessment was uploaded under the other one.
    const scoped = { ...extracts, assessment_extracts: [assessmentB] }
    const state = followSectionTotal(NO_LINK, scoped, "invoice-a", "a-parts")
    expect(state.link).toBeNull()
    expect(state.scroll).toBeNull()
    expect(state.notice).toEqual({ invoiceLineId: "a-parts", gap: "off-screen" })
    expect(invoiceTable(state, scoped)).toContain(
      "The paired engineer assessment is not on this screen"
    )
  })

  it("puts the notice under the line that was clicked, not another", () => {
    const html = invoiceTable(
      followSectionTotal(NO_LINK, extracts, "invoice-a", "a-paint")
    )
    const notice = html.indexOf("prints this section as a total only")
    expect(notice).toBeGreaterThan(html.indexOf("Total Paint & Materials"))
    expect(notice).toBeLessThan(html.indexOf("Additional charges"))
  })
})

describe("the association columns jump between the two tables", () => {
  it("the associated engineer assessment number jumps down unfiltered", () => {
    const state = followAssessmentNumber(NO_LINK, extracts, "invoice-a")
    expect(state.link).toEqual({
      assessmentId: "assessment-a",
      invoiceId: "invoice-a",
      invoiceLineId: null,
      breakdown: null,
    })
    expect(state.scroll?.elementIds).toEqual([
      linkRowIds.assessment("assessment-a"),
    ])
    const html = assessmentTable(state)
    expect(html).toContain("Bumper cover")
    expect(html).toContain("Bumper paint")
    expect(html).toContain("Back to invoice 343653726836/1~3538")
  })

  it("the associated invoice number jumps up to that invoice's row", () => {
    const state = followInvoiceNumber(NO_LINK, extracts, "assessment-a")
    expect(state.focusedInvoiceId).toBe("invoice-a")
    expect(state.scroll?.elementIds).toEqual([linkRowIds.invoice("invoice-a")])
  })

  it("follows a pair whose invoice printed no number", () => {
    const state = followInvoiceNumber(NO_LINK, extracts, "assessment-b")
    expect(state.focusedInvoiceId).toBe("invoice-b")
  })

  it("does not jump from an unpaired invoice", () => {
    expect(followAssessmentNumber(NO_LINK, extracts, "invoice-u")).toBe(NO_LINK)
  })

  it("does not jump to an invoice this screen does not show", () => {
    const scoped = { ...extracts, invoice_extracts: [invoiceA, invoiceUnpaired] }
    expect(followInvoiceNumber(NO_LINK, scoped, "assessment-b")).toBe(NO_LINK)
  })
})

describe("a paired row whose partner printed no number is still paired", () => {
  it("resolves the partner of a paired engineer assessment with no invoice number", () => {
    expect(assessmentPartner(extracts, assessmentB)).toEqual({
      paired: true,
      number: null,
      id: "invoice-b",
      onScreen: true,
    })
  })

  it("resolves the partner of an invoice whose engineer assessment printed no number", () => {
    const noNumber = {
      ...extracts,
      invoice_extracts: [{ ...invoiceA, paired_assessment_number: null }],
      assessment_extracts: [{ ...assessmentA, assessment_number: null }],
    }
    expect(invoicePartner(noNumber, noNumber.invoice_extracts[0])).toEqual({
      paired: true,
      number: null,
      id: "assessment-a",
      onScreen: true,
    })
  })

  it("never reads 'Not paired' in the engineer assessment table", () => {
    const html = assessmentTable(NO_LINK)
    expect(html).not.toContain("Not paired")
    expect(html).toContain("Paired · invoice number not extracted")
  })

  it("never reads 'Not paired' in the invoice table", () => {
    const noNumber = {
      ...extracts,
      invoice_extracts: [{ ...invoiceA, paired_assessment_number: null }],
      assessment_extracts: [{ ...assessmentA, assessment_number: null }],
    }
    const html = invoiceTable(NO_LINK, noNumber)
    expect(html).not.toContain("Not paired")
    expect(html).toContain(
      "Paired · engineer assessment number not extracted"
    )
  })

  it("keeps the missing-number cell clickable", () => {
    const html = renderToStaticMarkup(
      createElement(
        TooltipProvider,
        null,
        createElement(AssessmentExtractsTable, {
          assessments: extracts.assessment_extracts,
          linking: linking(NO_LINK),
        })
      )
    )
    expect(html).toMatch(
      /<button[^>]*aria-label="Go to the paired invoice \(number not extracted\)"/
    )
  })

  it("still says 'Not paired' for a row that genuinely is not", () => {
    expect(invoiceTable(NO_LINK)).toContain("Not paired")
  })
})
