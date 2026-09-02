import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { ClaimInvoiceSummary } from "@/lib/api"
import { ChallengedInvoicesSummary } from "./screens-review-findings"

function invoice(id: string, amount: number): ClaimInvoiceSummary {
  return {
    id,
    invoice_number: id,
    invoice_date: "2026-03-05",
    document_filename: `${id}.pdf`,
    supplier_name: "Test repairer",
    totals: { gross: 100 },
    challenge_review: { positive: 1, approved: 0, rejected: 0, unresolved: 1 },
    lines: [],
    challenge_lines: [
      {
        id: `challenge-${id}`,
        line_id: `line-${id}`,
        description: "Spark Plugs",
        billed_net: 100,
        supported_net: 100 - amount,
        in_house_p90_net: null,
        historical_claims_p90_net: 100 - amount,
        external_price_net: null,
        challenge_net: amount,
        status: "review",
        benchmark_source: "historical",
      },
    ],
  }
}

describe("challenged invoices table", () => {
  it("shows Invoice first, Challenge amount second, without duplicating the invoice column", () => {
    const html = renderToStaticMarkup(
      createElement(ChallengedInvoicesSummary, {
        invoices: [invoice("9510", 40)],
        onOpenInvoice: () => {},
      })
    )
    const headers = [...html.matchAll(/<th\b[^>]*>(.*?)<\/th>/g)].map(
      (match) => match[1]
    )
    expect(headers).toEqual([
      "Invoice",
      "Challenge amount",
      "Repair item",
      "Billed price",
      "In-house benchmark P90",
      "Historical claims P90",
      "External reference price",
      "Supported price",
      "Repairer",
      "Invoice date",
      "Status",
    ])
    const body = html.split("<tbody")[1]
    const cells = [...body.matchAll(/<td\b[^>]*>(.*?)<\/td>/g)].map((match) =>
      match[1].replace(/<[^>]*>/g, "")
    )
    expect(cells.slice(0, 3)).toEqual(["9510", "£40.00", "Spark Plugs"])
  })

  it("preserves descending challenge order, invoice filename fallback and empty-table span", () => {
    const low = invoice("9509", 20)
    const high = { ...invoice("9510", 40), invoice_number: null }
    const html = renderToStaticMarkup(
      createElement(ChallengedInvoicesSummary, {
        invoices: [low, high],
        onOpenInvoice: () => {},
      })
    ).split("<tbody")[1]
    expect(html.indexOf("9510.pdf")).toBeLessThan(html.indexOf("9509"))
    const empty = renderToStaticMarkup(
      createElement(ChallengedInvoicesSummary, {
        invoices: [],
        onOpenInvoice: () => {},
      })
    )
    expect(empty).toContain('colSpan="11"')
    expect(empty).toContain("No challenged invoice lines match these filters.")
  })
})
