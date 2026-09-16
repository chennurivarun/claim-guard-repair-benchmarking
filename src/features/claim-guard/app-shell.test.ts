import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { TooltipProvider } from "@/components/ui/tooltip"
import { AppShell } from "./app-shell"
import { documentIntelligenceViews } from "./types"
import type { ScreenId } from "./types"

// The SidebarMenuButton for the active entry carries data-active="true" on
// its opening <button> tag, ahead of a (very long, Tailwind-merged)
// className, the icon svg and finally the label <span>. Walk back to the
// nearest enclosing <button ...> to check its attributes reliably.
function isMarkedActiveNear(html: string, label: string) {
  const labelIndex = html.indexOf(label)
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

describe("primary sidebar navigation", () => {
  it("no longer lists the retired 'Source documents', 'Review extraction' or 'Invoice outcome & evidence' entries", () => {
    const html = renderShell("upload-processing")

    expect(html).not.toContain("Source documents")
    expect(html).not.toContain("Review extraction")
    expect(html).not.toContain("Invoice outcome & evidence")
  })

  it("keeps every other primary entry untouched", () => {
    const html = renderShell("upload-processing")

    expect(html).toContain("Benchmark data setup")
    expect(html).toContain("Document Intelligence")
    expect(html).toContain("Repair Price Benchmarking")
    expect(html).toContain("In-house Benchmark")
    expect(html).toContain("Challenged invoices")
    expect(html).toContain("Challenge decision")
    expect(html).toContain("Knowledge graph")
  })

  it("still highlights Document Intelligence as active for the document-pages and extracted-invoice sub-views", () => {
    const documentPagesHtml = renderShell("document-pages")
    const extractedInvoiceHtml = renderShell("extracted-invoice")

    expect(isMarkedActiveNear(documentPagesHtml, "Document Intelligence")).toBe(
      true
    )
    expect(
      isMarkedActiveNear(extractedInvoiceHtml, "Document Intelligence")
    ).toBe(true)
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
