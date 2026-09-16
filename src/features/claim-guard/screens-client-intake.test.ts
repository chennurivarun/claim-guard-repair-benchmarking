import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { TooltipProvider } from "@/components/ui/tooltip"
import { ClientIntakeScreen } from "./screens-client-intake"

// SSR markup only: `renderToStaticMarkup` never runs effects, so nothing in
// this file touches the network. That cuts both ways -- the extracts arrive
// from `fetchClaimExtracts` in an effect, so what these tests can prove is
// that the section is *mounted on this screen*, in its loading state, rather
// than living only on Review findings under Advanced tools.
function renderIntake(setup: boolean) {
  return renderToStaticMarkup(
    createElement(
      TooltipProvider,
      null,
      createElement(ClientIntakeScreen, {
        caseReference: "CG-2026-0048",
        setup,
        finalised: false,
        onProcessed: async () => {},
        onContinue: () => {},
        onOpenManualReview: () => {},
      })
    )
  )
}

describe("the extracts tables live on Document Intelligence", () => {
  it("mounts the invoice and assessment extracts section on the live screen", () => {
    const html = renderIntake(false)

    expect(html).toContain("Document Intelligence")
    expect(html).toContain("Invoice and assessment extracts")
    expect(html).toContain(
      "The two standardised tables from the invoice and assessment documents"
    )
    expect(html).toContain("Loading invoice and assessment extracts")
  })

  it("keeps the extracts off Benchmark data setup, whose tables are reference data", () => {
    const html = renderIntake(true)

    expect(html).toContain("Benchmark data setup")
    expect(html).not.toContain("Invoice and assessment extracts")
  })
})

describe("a folder of invoices and a folder of estimates, handed over together", () => {
  it("accepts many repair invoices and many engineer estimates", () => {
    const html = renderIntake(false)

    expect(html).toContain("Repair invoices (required)")
    expect(html).toContain("Engineer estimates (optional)")
    // Four file inputs: files + folder, for each of the two kinds. Every one
    // of them is `multiple`, so the single-file form is gone on both sides.
    expect(html.match(/multiple=""/g) ?? []).toHaveLength(4)
  })

  it("offers a directory picker beside each file picker", () => {
    const html = renderIntake(false)

    expect(html.match(/webkitdirectory=""/g) ?? []).toHaveLength(2)
    expect(html).toContain('aria-label="New repair invoices folder"')
    expect(html).toContain('aria-label="Engineer estimates folder"')
  })

  it("says the whole set goes over at once", () => {
    const html = renderIntake(false)

    expect(html).toContain("Hand over a whole set at once")
    expect(html).toContain("Upload invoices and estimates")
  })
})
