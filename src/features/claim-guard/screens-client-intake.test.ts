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

// The sweep is the one step of a hand-over that can fail on its own without
// losing a file. Before this, a failed sweep left a notice and no way out of
// it: there was no re-run control anywhere on the screen, so the only route
// back to a paired case was uploading every file again.
describe("a failed pairing sweep can be re-run without re-uploading", () => {
  it("offers a standing re-run control on Document Intelligence", () => {
    const html = renderIntake(false)

    expect(html).toContain("Re-run pairing sweep")
    expect(html).toContain(
      "Re-pairs every invoice and engineer estimate already in this claim"
    )
  })

  it("keeps it off Benchmark data setup, whose case has no live pairing", () => {
    expect(renderIntake(true)).not.toContain("Re-run pairing sweep")
  })
})

describe("the screen no longer describes itself as a demonstration", () => {
  it("does not set an invoice aside for a demo that no longer exists", () => {
    const html = renderIntake(true)

    expect(html).not.toContain("live demonstration")
    expect(html).toContain(
      "Keep one fresh invoice aside to run through Document Intelligence."
    )
  })
})
