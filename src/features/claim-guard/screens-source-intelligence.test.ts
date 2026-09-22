import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { TooltipProvider } from "@/components/ui/tooltip"
import type { IntakeGroup } from "./document-api"
import { ClientIntakeScreen } from "./screens-client-intake"
import { SourceIntelligenceScreen } from "./screens-source-intelligence"

// SSR markup only: no effect runs, so nothing here reaches the network. The
// requests these screens make are asserted in `benchmark-api.test.ts`; what
// this file proves is that each source's screen is built from the shared
// pieces and scoped to its own bucket.

function renderUpload(scope: IntakeGroup) {
  return renderToStaticMarkup(
    createElement(
      TooltipProvider,
      null,
      createElement(ClientIntakeScreen, {
        caseReference: "CG-2026-0048",
        setup: false,
        scope,
        finalised: false,
        onProcessed: async () => {},
        onContinue: () => {},
        onOpenManualReview: () => {},
      })
    )
  )
}

function renderIntelligence(intakeGroup: IntakeGroup) {
  return renderToStaticMarkup(
    createElement(
      TooltipProvider,
      null,
      createElement(SourceIntelligenceScreen, {
        caseReference: "CG-2026-0048",
        intakeGroup,
        finalised: false,
        onOpenBenchmarks: () => {},
      })
    )
  )
}

describe("Upload documents, per source", () => {
  it("offers one bucket, named for the source", () => {
    const html = renderUpload("in_house")

    expect(html).toContain("Insurer TP invoices – Model training")
    expect(html).not.toContain("Insurer TP invoices</")
    expect(html).not.toContain("Upload new invoice – Compare benchmark")
  })

  it("takes repair invoices and engineer assessments, files or a folder, on both slots", () => {
    const html = renderUpload("historical_claim")

    expect(html).toContain("Repair invoices")
    expect(html).toContain("Engineer assessments (optional)")
    expect(html.match(/multiple=""/g) ?? []).toHaveLength(4)
    expect(html.match(/webkitdirectory=""/g) ?? []).toHaveLength(2)
    expect(html).toContain("Upload invoices and engineer assessments")
  })

  it("leaves the extract tables to Document intelligence", () => {
    const html = renderUpload("historical_claim")

    expect(html).not.toContain("Invoice and engineer assessment extracts")
    expect(html).not.toContain("Consolidated client data")
  })

  it("names the step that follows", () => {
    expect(renderUpload("live")).toContain("Go to Document intelligence")
  })
})

describe("Document intelligence, per source", () => {
  it("leads with the mapping review for that source", () => {
    const html = renderIntelligence("historical_claim")

    expect(html).toContain("Insurer TP invoices")
    expect(html).toContain("Mapping review")
    expect(html).toContain("Approve mapping")
    expect(html).toContain("Mapping not approved yet")
  })

  it("shows extracted documents before pairing approval", () => {
    const html = renderIntelligence("in_house")

    expect(html).toContain("Review extracted documents and proposed pairs")
    expect(html).toContain("Loading invoice and engineer assessment extracts")
    expect(html.indexOf("Approve mapping")).toBeLessThan(
      html.indexOf("Review extracted documents and proposed pairs")
    )
  })

  it("names the new invoice's screen for the new invoice", () => {
    expect(renderIntelligence("live")).toContain(
      "Upload new invoice – Compare benchmark"
    )
  })
})
