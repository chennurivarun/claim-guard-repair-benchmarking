import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { TooltipProvider } from "@/components/ui/tooltip"
import {
  benchmarkAnalysis,
  analysisLines,
  templateDraft,
} from "./benchmark-fixtures"
import {
  benchmarkCellState,
  challengeSummary,
  documentOrder,
  generatedByLabel,
  mailtoHref,
  sortByChallengeLevel,
} from "./benchmark-analysis-rows"
import type { BenchmarkAnalysisPayload } from "./benchmark-api"
import {
  BenchmarkAnalysisView,
  ChallengeEmailDraftView,
} from "./screens-benchmark-analysis"

function render(
  analysis: BenchmarkAnalysisPayload = benchmarkAnalysis,
  extra: Record<string, unknown> = {}
) {
  return renderToStaticMarkup(
    createElement(
      TooltipProvider,
      null,
      createElement(BenchmarkAnalysisView, {
        analysis,
        onSelectInvoice: () => {},
        onDraftEmail: () => {},
        drafting: false,
        ...extra,
      })
    )
  )
}

/** Line ids in the order the table rows render them. */
function renderedLineOrder(html: string) {
  return [...html.matchAll(/data-line-id="([^"]+)"/g)].map((match) => match[1])
}

describe("line order: from the invoice first, then from the engineer assessment", () => {
  it("puts every invoice line before every assessment line, keeping each document's own order", () => {
    expect(documentOrder(analysisLines).map((line) => line.line_id)).toEqual([
      "inv-low",
      "inv-medium",
      "inv-high",
      "ea-1",
      "ea-medium",
      "ea-none",
    ])
  })

  it("renders the table in that order by default", () => {
    expect(renderedLineOrder(render())).toEqual([
      "inv-low",
      "inv-medium",
      "inv-high",
      "ea-1",
      "ea-medium",
      "ea-none",
    ])
  })

  it("shows where each row came from", () => {
    const html = render()
    const rowOf = (id: string) => {
      const start = html.indexOf(`data-line-id="${id}"`)
      return html.slice(start, html.indexOf("</tr>", start))
    }

    expect(rowOf("inv-high")).toContain("Invoice")
    expect(rowOf("ea-medium")).toContain("Engineer assessment")
  })
})

describe("sort by challenge level", () => {
  it("orders high, medium, low, none, then by challenge amount", () => {
    expect(sortByChallengeLevel(analysisLines).map((line) => line.line_id)).toEqual([
      "inv-high",
      "inv-medium", // medium, £100.00
      "ea-medium", // medium, £62.40
      "inv-low",
      "ea-1", // none: document order within the level
      "ea-none",
    ])
  })

  it("renders the sorted order when asked to", () => {
    expect(renderedLineOrder(render(benchmarkAnalysis, { initialSort: "level" }))).toEqual([
      "inv-high",
      "inv-medium",
      "ea-medium",
      "inv-low",
      "ea-1",
      "ea-none",
    ])
  })
})

describe("red where a benchmark is violated, amber for Low", () => {
  it("classifies each benchmark cell", () => {
    const [ea1, low, medium, high, eaMedium] = analysisLines

    expect(benchmarkCellState(high.benchmarks.third_party)).toBe("violated")
    expect(benchmarkCellState(high.benchmarks.aviva_dlg)).toBe("violated")
    expect(benchmarkCellState(medium.benchmarks.aviva_dlg)).toBe("within")
    expect(benchmarkCellState(low.benchmarks.third_party)).toBe("above")
    expect(benchmarkCellState(low.benchmarks.aviva_dlg)).toBe("no-data")
    expect(benchmarkCellState(eaMedium.benchmarks.third_party)).toBe("no-data")
    expect(benchmarkCellState(ea1.benchmarks.third_party)).toBe("within")
  })

  it("draws a violated cell red, and only a violated cell", () => {
    const html = render()
    const red = [...html.matchAll(/<td[^>]*data-benchmark-state="violated"[^>]*>/g)]

    // high: both; medium: third party; ea-medium: Aviva DLG.
    expect(red).toHaveLength(4)
    for (const match of red) expect(match[0]).toContain("text-destructive")
    const notRed = [
      ...html.matchAll(/<td[^>]*data-benchmark-state="(within|above|no-data)"[^>]*>/g),
    ]
    for (const match of notRed) expect(match[0]).not.toContain("text-destructive")
  })

  it("draws a Low line amber, and does not draw it red", () => {
    const html = render()
    const lowRow = html.match(/<tr[^>]*data-line-id="inv-low"[^>]*>/)?.[0] ?? ""

    expect(lowRow).toContain('data-level="low"')
    expect(lowRow).toContain("bg-amber")
    expect(lowRow).not.toContain("destructive")
  })
})

describe("an unavailable benchmark reads No data, never £0.00", () => {
  it("prints No data in every cell with no benchmark", () => {
    const html = render()
    const noData = [
      ...html.matchAll(/<td[^>]*data-benchmark-state="no-data"[^>]*>(.*?)<\/td>/g),
    ]

    // inv-low Aviva, ea-medium third party, ea-none both.
    expect(noData).toHaveLength(4)
    for (const match of noData) {
      expect(match[1]).toContain("No data")
      expect(match[1]).not.toContain("£0.00")
    }
  })

  it("prints n beside every P90 that exists", () => {
    const html = render()
    const cells = [
      ...html.matchAll(
        /<td[^>]*data-benchmark-state="(within|above|violated)"[^>]*>(.*?)<\/td>/g
      ),
    ]

    expect(cells.length).toBe(8)
    for (const match of cells) expect(match[2]).toMatch(/n = \d+/)
  })
})

describe("the total challenge amount counts High and Medium only", () => {
  it("sums the challenge amounts of high and medium lines, never low", () => {
    const summary = challengeSummary(analysisLines)

    expect(summary.total).toBeCloseTo(312.4, 2)
    expect(summary.counts).toEqual({ high: 1, medium: 2, low: 1 })
    expect(summary.challengeCount).toBe(3)
  })

  it("leaves a Low line out even if the server puts an amount on it", () => {
    // The contract sends "0.00" for Low, but the rule belongs to this screen:
    // a Low line's distance above P90 is never a challenge amount.
    const lines = analysisLines.map((line) =>
      line.line_id === "inv-low"
        ? { ...line, challenge: { ...line.challenge, challenge_amount: "47.73" } }
        : line
    )

    expect(challengeSummary(lines).total).toBeCloseTo(312.4, 2)
  })

  it("puts the total and the count per level at the top of the screen", () => {
    const html = render()
    const table = html.indexOf('data-testid="analysis-table"')
    const total = html.indexOf("£312.40")

    expect(total).toBeGreaterThan(-1)
    expect(total).toBeLessThan(table)
    expect(html).toContain("Total challenge amount")
    const text = html.replaceAll("<!-- -->", "")
    expect(text).toContain("1 high")
    expect(text).toContain("2 medium")
    expect(text).toContain("1 low")
  })

  it("does not count a Low line's distance above P90", () => {
    const html = render()
    const lowRow = html.slice(
      html.indexOf('data-line-id="inv-low"'),
      html.indexOf("</tr>", html.indexOf('data-line-id="inv-low"'))
    )

    expect(lowRow).toContain("£47.73 above P90")
    expect(lowRow).toContain("not counted")
  })
})

describe("the invoice header", () => {
  it("names the invoice, vehicle, category and its source, and the paired engineer assessment", () => {
    const html = render()

    expect(html).toContain("LIVE-77")
    expect(html).toContain("SKODA KAROQ")
    expect(html).toContain("A30DRY")
    expect(html).toContain("SUV")
    expect(html).toContain("From the lookup")
    expect(html).toContain("D7576879")
  })

  it("offers a selector when there is more than one live invoice", () => {
    const html = render()

    expect(html).toContain('aria-label="New invoice to analyse"')
    expect(html).toContain("LIVE-78")
  })

  it("offers no selector for a single live invoice", () => {
    const html = render({
      ...benchmarkAnalysis,
      live_invoices: benchmarkAnalysis.live_invoices.slice(0, 1),
    })

    expect(html).not.toContain('aria-label="New invoice to analyse"')
  })

  it("marks an Unknown category as unknown", () => {
    const html = render({
      ...benchmarkAnalysis,
      invoice: {
        ...benchmarkAnalysis.invoice,
        vehicle_category: "Unknown",
        vehicle_category_source: "unknown",
      },
    })

    expect(html).toContain('data-category-unknown="true"')
    expect(html).toContain("Unknown category")
  })
})

describe("select challenges, then draft an email", () => {
  it("offers a checkbox on each challenge line and on no other", () => {
    const html = render()

    expect(html).toContain('aria-label="Select FRONT BUMPER for the challenge email"')
    expect(html).toContain('aria-label="Select PAINT REAR DOOR for the challenge email"')
    expect(html).toContain('aria-label="Select HEADLAMP for the challenge email"')
    expect(html).not.toContain('aria-label="Select L/R DOOR for the challenge email"')
    expect(html).not.toContain('aria-label="Select CLIPS for the challenge email"')
  })

  it("keeps Draft email disabled until something is selected", () => {
    const html = render()
    const button = html.match(/<button[^>]*>[^<]*Draft email/)?.[0] ?? ""

    expect(button).toContain('disabled=""')
  })

  it("enables Draft email once a challenge is selected", () => {
    const html = render(benchmarkAnalysis, { initialSelected: ["inv-high"] })
    const button = html.match(/<button[^>]*>[^<]*Draft email/)?.[0] ?? ""

    expect(button).toContain("Draft email")
    expect(button).not.toContain('disabled=""')
  })
})

describe("show evidence per line, for both benchmarks", () => {
  it("offers evidence on every line", () => {
    const html = render()

    expect(html).toContain("Show evidence for FRONT BUMPER")
    expect(html).toContain("Show evidence for CLIPS")
  })

  it("lists the contributing rows under each benchmark when open", () => {
    const html = render(benchmarkAnalysis, { initialEvidenceOpen: ["inv-high"] })

    expect(html).toContain("Third party insured invoices evidence")
    expect(html).toContain("Aviva DLG invoices evidence")
    expect(html).toContain("TP-1001")
  })
})

describe("the email draft says it is a draft, and never that it was sent", () => {
  function renderDraft(draft = templateDraft) {
    return renderToStaticMarkup(
      createElement(ChallengeEmailDraftView, {
        draft,
        onCopy: () => {},
      })
    )
  }

  it("carries the subject and the body", () => {
    const html = renderDraft()

    expect(html).toContain("Invoice LIVE-77: 2 line items challenged")
    expect(html).toContain("FRONT BUMPER: billed £600.00, justified £450.00.")
  })

  it("says plainly that nothing has been sent", () => {
    const html = renderDraft()

    expect(html).toContain("This is a draft. Nothing has been sent.")
    expect(html).not.toMatch(/\b(email|message) (was |has been )?sent\b/i)
    expect(html).not.toMatch(/\bsent to\b/i)
    expect(html).not.toMatch(/>\s*Send\s*</)
  })

  it("offers Copy and Open in email app, and nothing that sends", () => {
    const html = renderDraft()

    expect(html).toContain("Copy")
    expect(html).toContain("Open in email app")
    expect(html).toContain('href="mailto:')
  })

  it("says honestly who wrote it", () => {
    expect(renderDraft()).toContain("Written from a template")
    expect(renderDraft({ ...templateDraft, generated_by: "ai" })).toContain(
      "AI-written; every figure checked against the analysis"
    )
    expect(generatedByLabel("template")).toBe("Written from a template")
  })

  it("builds a mailto link with the subject and body encoded", () => {
    const href = mailtoHref("Invoice 1 & 2", "Line one\nLine two")

    expect(href).toBe("mailto:?subject=Invoice%201%20%26%202&body=Line%20one%0ALine%20two")
  })
})

describe("the rolled-up totals' breakdown is here now", () => {
  it("mounts SectionBreakdownDetail on the analysis screen", () => {
    const html = render()

    expect(html).toContain("Engineer assessment breakdown")
    expect(html).toContain("Total Parts")
    expect(html).toContain("HEADLAMP")
    expect(html).toContain("Matches engineer assessment")
  })

  it("says so when there is no rolled-up total to break down", () => {
    const html = render({ ...benchmarkAnalysis, section_breakdowns: [] })

    expect(html).not.toContain("Engineer assessment breakdown")
    expect(html).toContain("prints no rolled-up totals")
  })
})
