import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import {
  ApiUnavailablePanel,
  ConnectingPanel,
  NoClaimsPanel,
  WorkspaceErrorPanel,
} from "./workspace-state"
import {
  manualReviewUnavailableNotice,
  noWorkspaceNotice,
} from "./workspace-notices"

// Values from the retired demo workspace. None of them may appear on a screen
// that has no data to show.
const RETIRED_DEMO_VALUES = [
  "CG-2026-0048",
  "91283",
  "Northstar Mutual",
  "Wessex Assurance",
  "EK18 NXR",
  "PX64 XCU",
  "St Albans Car Clinic",
]

function expectNoFabricatedData(html: string) {
  for (const value of RETIRED_DEMO_VALUES) {
    expect(html).not.toContain(value)
  }
  // No table of any kind: an empty state must not look like data.
  expect(html).not.toContain("<table")
  // No money figures.
  expect(html).not.toMatch(/£\d/)
}

describe("loading state", () => {
  it("says it is loading and shows nothing that could be read as data", () => {
    const html = renderToStaticMarkup(createElement(ConnectingPanel))

    expect(html).toContain("Connecting to Price Benchmarking Model TP Repair")
    expect(html).toContain("Nothing is displayed until the database answers")
    expectNoFabricatedData(html)
  })
})

describe("no-claims state", () => {
  function render(starting = false) {
    return renderToStaticMarkup(
      createElement(NoClaimsPanel, {
        onStart: () => {},
        onRetry: () => {},
        starting,
      })
    )
  }

  // An empty database used to tell the user to upload documents on a page
  // that offered no upload control and no way to reach one.
  it("offers a button that starts a claim, instead of an instruction it cannot act on", () => {
    const html = render()

    expect(html).toContain("No claims yet")
    expect(html).toContain("Start a new claim")
    expect(html).toContain("Check again")
    expect(html).not.toContain("Upload a repair invoice")
    expectNoFabricatedData(html)
  })

  it("uses the client's term for the engineer's document", () => {
    const html = render()

    expect(html).not.toContain("engineer estimate")
  })

  it("cannot be clicked twice while a claim is being started", () => {
    const html = render(true)

    expect(html).toContain("Starting")
    expect(html).toMatch(/<button[^>]*disabled/)
  })
})

describe("workspace-error state", () => {
  it("names the claim and repeats the backend's reason, without claiming it is empty", () => {
    const html = renderToStaticMarkup(
      createElement(WorkspaceErrorPanel, {
        caseReference: "CG-CLIENT-001",
        message: "The selected invoice does not belong to this claim.",
        onRetry: () => {},
      })
    )

    expect(html).toContain("CG-CLIENT-001")
    expect(html).toContain(
      "The selected invoice does not belong to this claim."
    )
    // The two statements this panel exists to avoid making.
    expect(html).not.toContain("has no documents")
    expect(html).not.toContain("nothing has been extracted")
    expect(html).toContain("Try again")
    expectNoFabricatedData(html)
  })
})

// A document flagged for manual review on a claim with nothing extracted used
// to wire the intake screen's only escape hatch to a handler that changed no
// screen, showed no message and raised no error.
describe("notices shown when there is no workspace to open", () => {
  it("explains that manual review cannot open, and what to do instead", () => {
    const notice = manualReviewUnavailableNotice()

    expect(notice.title).toBeTruthy()
    expect(notice.description).toContain("Reprocess the document")
    // It must not imply the document is now under review.
    expect(notice.description).not.toMatch(/opening|opened/i)
  })

  it("explains that no review screen can be opened while nothing is loaded", () => {
    const notice = noWorkspaceNotice()

    expect(notice.title).toBeTruthy()
    expect(notice.description).toContain("extracted invoice")
    expect(notice.description).not.toBe(
      manualReviewUnavailableNotice().description
    )
  })
})

describe("API-unavailable state", () => {
  it("says the API is unavailable, repeats the reason and shows nothing else", () => {
    const html = renderToStaticMarkup(
      createElement(ApiUnavailablePanel, {
        message: "API returned 503.",
        onRetry: () => {},
      })
    )

    expect(html).toContain(
      "Price Benchmarking Model TP Repair API is unavailable"
    )
    expect(html).toContain("API returned 503.")
    expect(html).toContain("because none could be read")
    expect(html).toContain("Retry connection")
    expectNoFabricatedData(html)
  })
})
