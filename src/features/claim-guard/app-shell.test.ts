import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { TooltipProvider } from "@/components/ui/tooltip"
import { AppShell } from "./app-shell"
import { advancedTools, navigationSections } from "./navigation"
import { documentIntelligenceViews } from "./types"
import type { ScreenId } from "./types"

// This file locks the information architecture. Until 18 Sep it locked the
// flat list (Benchmark data setup, Document Intelligence, Mapping review, …).
// The benchmarks-and-challenges sprint replaces that on purpose with the
// structure Neha dictated on the 17 Sep walkthrough -- "two major headings.
// Insurer Third Party invoices and EXL/ In house Benchmark invoices. Under every heading
// … upload documents … document intelligence … benchmark computation", then
// a third heading, "upload new invoice". Everything that was primary before
// and is not part of her structure now sits under Advanced tools.

// The SidebarMenuButton for the active entry carries data-active="true" on
// its opening <button> tag, ahead of a (very long, Tailwind-merged)
// className, the icon svg and finally the label <span>. Walk back to the
// nearest enclosing <button ...> to check its attributes reliably.
function isMarkedActiveNear(html: string, label: string, from = 0) {
  const labelIndex = html.indexOf(label, from)
  if (labelIndex === -1) return false
  const buttonStart = html.lastIndexOf("<button", labelIndex)
  if (buttonStart === -1) return false
  return html.slice(buttonStart, labelIndex).includes('data-active="true"')
}

function renderShell(activeScreen: ScreenId) {
  return renderToStaticMarkup(
    createElement(
      TooltipProvider,
      null,
      createElement(AppShell, {
        activeScreen,
        onNavigate: () => {},
        issuanceAllowed: false,
        liabilityStatus: "PENDING",
        apiStatus: "connected",
        children: createElement("div", null, "content"),
      })
    )
  )
}

describe("the left navigation Neha described", () => {
  it("has three headings, in her order, each with its three sub-screens", () => {
    expect(
      navigationSections.map((section) => ({
        label: section.label,
        items: section.items.map((item) => [item.id, item.label]),
      }))
    ).toEqual([
      {
        label: "Insurer Third Party invoices",
        items: [
          ["tp-upload", "Upload documents"],
          ["tp-intelligence", "Document intelligence"],
          ["tp-benchmarks", "Benchmark computation"],
        ],
      },
      {
        label: "EXL/ In house Benchmark invoices",
        items: [
          ["dlg-upload", "Upload documents"],
          ["dlg-intelligence", "Document intelligence"],
          ["dlg-benchmarks", "Benchmark computation"],
        ],
      },
      {
        label: "Upload new invoice – Compare benchmark",
        items: [
          ["new-invoice-upload", "Upload"],
          ["new-invoice-intelligence", "Document intelligence"],
          ["benchmark-analysis", "Benchmark analysis"],
        ],
      },
    ])
  })

  it("renders the three headings in that order", () => {
    const html = renderShell("tp-upload")
    const thirdParty = html.indexOf("Insurer Third Party invoices")
    const aviva = html.indexOf("EXL/ In house Benchmark invoices")
    const newInvoice = html.indexOf("Upload new invoice – Compare benchmark")

    expect(thirdParty).toBeGreaterThan(-1)
    expect(aviva).toBeGreaterThan(thirdParty)
    expect(newInvoice).toBeGreaterThan(aviva)
    expect(html).toContain("Benchmark computation")
    expect(html).toContain("Benchmark analysis")
  })

  it("marks the sub-screen under the right heading active, not its namesake under the other", () => {
    const html = renderShell("dlg-intelligence")
    const aviva = html.indexOf("EXL/ In house Benchmark invoices")

    // The first "Document intelligence" is the third-party one.
    expect(isMarkedActiveNear(html, "Document intelligence")).toBe(false)
    expect(isMarkedActiveNear(html, "Document intelligence", aviva)).toBe(true)
  })

  it("puts Advanced tools after all three headings, closed by default", () => {
    const html = renderShell("tp-upload")

    expect(html.indexOf("Advanced tools")).toBeGreaterThan(
      html.indexOf("Upload new invoice")
    )
    // Closed: none of the moved screens is on the page.
    expect(html).not.toContain("Repair Price Benchmarking")
    expect(html).not.toContain("Challenge decision")
  })
})

describe("screens outside her structure move to Advanced tools", () => {
  it("keeps every screen that used to be primary, none deleted", () => {
    const ids = advancedTools.map((item) => item.id)

    for (const id of [
      "benchmark-setup",
      "upload-processing",
      "document-mapping",
      "benchmark-dashboard",
      "in-house-benchmarks",
      "price-comparison",
      "challenge-review",
      "knowledge-graph",
      "claim-liability",
      "review-findings-all",
      "ontology-mapping",
      "missing-items",
      "ontology-bank",
      "audit-reports",
    ] satisfies ScreenId[]) {
      expect(ids).toContain(id)
    }
  })

  it("carries none of her nine screens", () => {
    const primary = navigationSections.flatMap((section) =>
      section.items.map((item) => item.id)
    )
    for (const item of advancedTools) expect(primary).not.toContain(item.id)
  })

  it("opens itself when one of those screens is active", () => {
    const html = renderShell("benchmark-dashboard")

    expect(html).toContain("Repair Price Benchmarking")
    expect(html).toContain("Challenge decision")
    expect(isMarkedActiveNear(html, "Repair Price Benchmarking")).toBe(true)
  })

  it("keeps the old Document Intelligence sub-views highlighting their entry", () => {
    const html = renderShell("document-pages")

    expect(isMarkedActiveNear(html, "Document Intelligence (whole claim)")).toBe(
      true
    )
  })

  it("no longer lists the retired 'Source documents', 'Review extraction' or 'Invoice outcome & evidence' entries", () => {
    const html = renderShell("upload-processing")

    expect(html).not.toContain("Source documents")
    expect(html).not.toContain("Review extraction")
    expect(html).not.toContain("Invoice outcome & evidence")
  })
})

describe("Document Intelligence view selector", () => {
  it("offers exactly the Document Intelligence, Source documents and Review extraction options, in that order", () => {
    expect(documentIntelligenceViews).toEqual([
      { id: "upload-processing", label: "Document Intelligence" },
      { id: "document-pages", label: "Source documents" },
      { id: "extracted-invoice", label: "Review extraction" },
    ])
  })
})
