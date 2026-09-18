import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { TooltipProvider } from "@/components/ui/tooltip"
import { AppShell } from "./app-shell"
import { ClientIntakeScreen } from "./screens-client-intake"
import { DocumentMappingScreen } from "./screens-document-mapping"

// SSR markup only: `renderToStaticMarkup` never runs effects, so nothing here
// touches the network. What it can prove is that the step exists, that it
// leads with the approval state rather than with a table, and -- on the
// intake screen -- that the control Neha objected to is gone.

function renderMapping() {
  return renderToStaticMarkup(
    createElement(
      TooltipProvider,
      null,
      createElement(DocumentMappingScreen, {
        caseReference: "CG-2026-0048",
        finalised: false,
        onContinue: () => {},
      })
    )
  )
}

function renderIntake() {
  return renderToStaticMarkup(
    createElement(
      TooltipProvider,
      null,
      createElement(ClientIntakeScreen, {
        caseReference: "CG-2026-0048",
        setup: false,
        finalised: false,
        onProcessed: async () => {},
        onContinue: () => {},
        onOpenManualReview: () => {},
      })
    )
  )
}

describe("the mapping review step", () => {
  it("offers the approve action and says the mapping is not approved yet", () => {
    const html = renderMapping()

    expect(html).toContain("Mapping review")
    expect(html).toContain("Approve mapping")
    expect(html).toContain("Mapping not approved yet")
    // The sequence Neha asked for: approve, then the documents are read,
    // then the extracts. The extracts are not offered before approval.
    expect(html).toContain("View extracts")
    expect(html).toContain("disabled")
  })

  it("never prints a pairing percentage", () => {
    // Pairing confidence is 1.0 for every automatic pair by construction,
    // so a percentage would be a number that is always the same.
    expect(renderMapping()).not.toContain("% pairing")
  })
})

describe("the retired re-run control", () => {
  it("is gone from Document Intelligence", () => {
    const html = renderIntake()

    expect(html).not.toContain("Re-run pairing sweep")
    expect(html).not.toContain("Re-running pairing sweep")
    // The upload flow itself is untouched.
    expect(html).toContain("Document Intelligence")
    expect(html).toContain("Upload invoices and engineer assessments")
  })
})

// Since the 18 Sep navigation change the whole-claim Mapping review is an
// Advanced tool: each source's Document intelligence carries its own mapping
// step now. It is still reachable, and still opens its group when active.
describe("the sidebar carries the whole-claim mapping step", () => {
  it("lists Mapping review under Advanced tools, beside the other moved screens", () => {
    const html = renderToStaticMarkup(
      createElement(
        TooltipProvider,
        null,
        createElement(AppShell, {
          activeScreen: "document-mapping",
          onNavigate: () => {},
          issuanceAllowed: false,
          liabilityStatus: "PENDING",
          apiStatus: "connected",
          children: createElement("div", null, "content"),
        })
      )
    )

    expect(html).toContain("Mapping review")
    expect(html).toContain("Document Intelligence (whole claim)")
    expect(html).toContain("Repair Price Benchmarking")
    expect(html.indexOf("Mapping review")).toBeGreaterThan(
      html.indexOf("Advanced tools")
    )
  })
})
