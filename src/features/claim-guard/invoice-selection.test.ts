import { describe, expect, it } from "vitest"

import type { ClaimInvoiceSummary } from "@/lib/api"
import {
  challengedInvoices,
  invoiceOptionsForScreen,
  preferredInvoiceIdForScreen,
} from "./invoice-selection"

function invoice(id: string, positive: number): ClaimInvoiceSummary {
  return {
    id,
    invoice_number: id,
    invoice_date: null,
    document_filename: `${id}.pdf`,
    supplier_name: null,
    totals: { gross: null },
    challenge_review: {
      positive,
      approved: 0,
      rejected: 0,
      unresolved: positive,
    },
    lines: [],
  }
}

describe("invoice review selection", () => {
  const invoices = [invoice("clean", 0), invoice("challenged", 2)]

  it("keeps clean invoices out of the challenged-invoices dropdown", () => {
    expect(challengedInvoices(invoices).map((item) => item.id)).toEqual([
      "challenged",
    ])
    expect(
      invoiceOptionsForScreen(invoices, "price-comparison").map(
        (item) => item.id
      )
    ).toEqual(["challenged"])
  })

  it("keeps every invoice in advanced review findings", () => {
    expect(
      invoiceOptionsForScreen(invoices, "review-findings-all").map(
        (item) => item.id
      )
    ).toEqual(["clean", "challenged"])
  })

  it("uses the same challenged invoices in challenge decision", () => {
    expect(
      invoiceOptionsForScreen(invoices, "challenge-review").map(
        (item) => item.id
      )
    ).toEqual(["challenged"])
  })

  it("moves to the first challenged invoice when the current invoice is clean", () => {
    expect(
      preferredInvoiceIdForScreen(invoices, "price-comparison", "clean")
    ).toBe("challenged")
  })
})
