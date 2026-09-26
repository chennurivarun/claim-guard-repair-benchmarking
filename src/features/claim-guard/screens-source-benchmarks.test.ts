import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { TooltipProvider } from "@/components/ui/tooltip"
import {
  emptyAvivaBenchmarks,
  thirdPartyBenchmarks,
} from "./benchmark-fixtures"
import type { SourceBenchmarksPayload } from "./benchmark-api"
import { SourceBenchmarksView } from "./screens-source-benchmarks"

function render(
  payload: SourceBenchmarksPayload | null,
  extra: Record<string, unknown> = {}
) {
  return renderToStaticMarkup(
    createElement(
      TooltipProvider,
      null,
      createElement(SourceBenchmarksView, {
        payload,
        loading: false,
        error: null,
        onUpload: () => {},
        ...extra,
      })
    )
  )
}

function p90Cells(html: string) {
  return [...html.matchAll(/<td[^>]*data-testid="p90-cell"[^>]*>(.*?)<\/td>/g)].map(
    (match) => match[1]
  )
}

describe("benchmark computation: category · repair item · n · P90 · median · min · max", () => {
  it("heads the table with the columns she asked for, n before P90", () => {
    const page = render(thirdPartyBenchmarks)
    const html = page.slice(page.indexOf('data-testid="benchmark-table"'))
    const headings = [
      "Vehicle category",
      "Repair item",
      ">n<",
      "P90",
      "Median",
      "Min",
      "Max",
    ].map((label) => html.indexOf(label))

    for (const index of headings) expect(index).toBeGreaterThan(-1)
    expect([...headings].sort((a, b) => a - b)).toEqual(headings)
  })

  it("prints n inside every P90 cell, so one observation never reads as a population", () => {
    const cells = p90Cells(render(thirdPartyBenchmarks))

    expect(cells).toHaveLength(2)
    expect(cells[0]).toContain("£412.50")
    expect(cells[0]).toContain("n = 3")
    expect(cells[1]).toContain("£780.00")
    expect(cells[1]).toContain("n = 1")
    expect(cells[1]).toContain("single observation")
  })

  it("prints the median, min and max", () => {
    const html = render(thirdPartyBenchmarks)

    expect(html).toContain("£380.00")
    expect(html).toContain("£350.00")
    expect(html).toContain("£420.00")
  })
})

describe("vehicle categories and where they came from (D2)", () => {
  it("lists each category with its source", () => {
    const html = render(thirdPartyBenchmarks)

    expect(html).toContain("SUV")
    expect(html).toContain("From the lookup")
    expect(html).toContain("Hatchback")
    expect(html).toContain("AI-assigned")
  })

  it("marks Unknown as an unknown, not as a real vehicle class", () => {
    const html = render(thirdPartyBenchmarks)

    expect(html).toContain('data-category-unknown="true"')
    expect(html).toContain("Unknown category")
    expect(html).toContain("make and model not recognised")
    // The known classes are never flagged.
    expect(html.match(/data-category-unknown="true"/g)?.length).toBe(
      html.match(/Unknown category/g)?.length
    )
  })

  it("never draws the unknown category as a plain class badge", () => {
    const html = render(thirdPartyBenchmarks)
    // The benchmark row for the unknown vehicle carries the marker too.
    const item = html.indexOf(">Rear door<")
    const row = html.slice(html.lastIndexOf("<tr", item), item)
    expect(row).toContain('data-category-unknown="true"')
    // …and the SUV row does not.
    const suv = html.indexOf(">Front bumper<")
    expect(html.slice(html.lastIndexOf("<tr", suv), suv)).not.toContain(
      "data-category-unknown"
    )
  })
})

describe("evidence per row", () => {
  it("offers the contributing rows for each benchmark row", () => {
    const html = render(thirdPartyBenchmarks)

    expect(html).toContain("Show evidence for Front bumper (SUV)")
    expect(html).toContain("Show evidence for Rear door (Unknown)")
  })

  it("names every contributing invoice when open, with its origin", () => {
    const html = render(thirdPartyBenchmarks, { evidenceOpen: "all" })

    expect(html).toContain("TP-1001")
    expect(html).toContain("TP-1002")
    expect(html).toContain("TP-1003")
    expect(html).toContain("Engineer assessment")
    expect(html).toContain("A30DRY")
  })
})

describe("a source with no documents yet", () => {
  it("says so, and offers the upload, instead of an empty table", () => {
    const html = render(emptyAvivaBenchmarks)

    expect(html).toContain("No EXL/ In house Benchmark invoices uploaded yet")
    expect(html).toContain("Upload documents")
    expect(html).not.toContain('data-testid="p90-cell"')
  })
})
