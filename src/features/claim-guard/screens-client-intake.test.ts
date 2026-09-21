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
    expect(html).toContain("Invoice and engineer assessment extracts")
    expect(html).toContain(
      "The two standardised tables from the invoice and engineer assessment documents"
    )
    expect(html).toContain("Loading invoice and engineer assessment extracts")
  })

  it("keeps the extracts off Benchmark data setup, whose tables are reference data", () => {
    const html = renderIntake(true)

    expect(html).toContain("Benchmark data setup")
    expect(html).not.toContain("Invoice and engineer assessment extracts")
  })
})

describe("a folder of invoices and a folder of engineer assessments, handed over together", () => {
  it("accepts many repair invoices and many engineer assessments", () => {
    const html = renderIntake(false)

    expect(html).toContain("Repair invoices (required)")
    expect(html).toContain("Engineer assessments (optional)")
    // Four file inputs: files + folder, for each of the two kinds. Every one
    // of them is `multiple`, so the single-file form is gone on both sides.
    expect(html.match(/multiple=""/g) ?? []).toHaveLength(4)
  })

  it("offers a directory picker beside each file picker", () => {
    const html = renderIntake(false)

    expect(html.match(/webkitdirectory=""/g) ?? []).toHaveLength(2)
    expect(html).toContain('aria-label="New repair invoices folder"')
    expect(html).toContain('aria-label="Engineer assessments folder"')
  })

  it("says the whole set goes over at once", () => {
    const html = renderIntake(false)

    expect(html).toContain("Hand over a whole set at once")
    expect(html).toContain("Upload invoices and engineer assessments")
  })

  it("keeps the assessment picker on the benchmark setup screen", () => {
    const html = renderIntake(true)

    expect(html).toContain("Engineer assessments (optional)")
    expect(html).toContain("Upload invoices and engineer assessments")
    expect(html.match(/multiple=""/g) ?? []).toHaveLength(8)
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

// 17 Sep walkthrough, §1. "What do you mean, nine invoices extracted? …
// remove it." The counter read "16 documents processed · 9 invoices
// extracted" and nobody on the call could explain the 9.
describe("Document Intelligence stops claiming things it cannot explain", () => {
  it("no longer counts invoices extracted", () => {
    expect(renderIntake(false)).not.toContain("invoices extracted")
    expect(renderIntake(true)).not.toContain("invoices extracted")
  })

  it("keeps the documents-processed count, which is one row per file handed over", () => {
    expect(renderIntake(false)).toContain("documents processed")
  })

  it("drops the Live invoices card", () => {
    const html = renderIntake(false)

    expect(html).not.toContain("Live invoices")
    expect(html).not.toContain(
      "Live invoices remain outside the reference dataset"
    )
  })

  it("keeps the reference-dataset table on Benchmark data setup", () => {
    const html = renderIntake(true)

    expect(html).toContain("Consolidated client data")
    expect(html).toContain("Stored extraction from the selected client dataset")
  })

})

// §3.1: "she checked the documents and they say assessment, so the full
// phrase is engineer assessment".
describe("the screen calls it an engineer assessment", () => {
  it("labels the second picker and its folder engineer assessments", () => {
    const html = renderIntake(false)

    expect(html).toContain("Engineer assessments (optional)")
    expect(html).toContain('aria-label="Engineer assessments folder"')
    expect(html).not.toContain("Engineer estimates")
  })

  it("names both kinds on the upload button", () => {
    expect(renderIntake(false)).toContain(
      "Upload invoices and engineer assessments"
    )
  })

  it("asks for engineer assessments in the card copy", () => {
    expect(renderIntake(false)).toContain(
      "every engineer assessment that goes with them"
    )
    expect(renderIntake(true)).toContain(
      "their corresponding engineer assessments"
    )
  })
})
