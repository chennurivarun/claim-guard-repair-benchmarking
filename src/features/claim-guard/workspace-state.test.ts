import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import {
  ApiUnavailablePanel,
  ConnectingPanel,
  NoClaimsPanel,
} from "./workspace-state"

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

    expect(html).toContain("Connecting to ClaimGuard")
    expect(html).toContain("Nothing is displayed until the database answers")
    expectNoFabricatedData(html)
  })
})

describe("no-claims state", () => {
  it("tells the user to upload documents and offers a re-check", () => {
    const html = renderToStaticMarkup(
      createElement(NoClaimsPanel, { onRetry: () => {} })
    )

    expect(html).toContain("No claims yet")
    expect(html).toContain("The database holds no claims")
    expect(html).toContain("Upload a repair invoice")
    expect(html).toContain("Check again")
    expectNoFabricatedData(html)
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

    expect(html).toContain("ClaimGuard API is unavailable")
    expect(html).toContain("API returned 503.")
    expect(html).toContain("because none could be read")
    expect(html).toContain("Retry connection")
    expectNoFabricatedData(html)
  })
})
