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

// The standing "Re-run pairing sweep" control is gone from both variants of
// this screen. Neha's objection was to re-running as a substitute for human
// correction -- "you cannot keep on rerunning indefinitely; somewhere you
// need to stop and manually correct the things" -- so the sweep now runs when
// the handler approves the mapping on Mapping review, against the pairs they
// confirmed. The way out of a failed sweep is still there; it is now a
// decision rather than a retry.
describe("the standing re-run control is retired", () => {
  it("is offered on neither Document Intelligence nor Benchmark data setup", () => {
    expect(renderIntake(false)).not.toContain("Re-run pairing sweep")
    expect(renderIntake(true)).not.toContain("Re-run pairing sweep")
  })

  it("points a failed sweep at the mapping approval instead of at itself", () => {
    // The notice used to end "until the sweep is re-run below", which named
    // a button that no longer exists.
    expect(renderIntake(false)).not.toContain("until the sweep is re-run below")
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
