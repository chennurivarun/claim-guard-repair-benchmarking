import { describe, expect, it } from "vitest"

import app from "./App.tsx?raw"

// App.tsx is wired to the live API and cannot be rendered in a unit test, so
// the two guards below are asserted against its source. Both exist because
// the screen arms are chosen on `bootstrap.status`, not on `activeScreen`:
// changing the active screen while there is no workspace moves nothing on
// screen now, and silently relocates the user once a workspace arrives.

function functionBody(source: string, signature: string) {
  const start = source.indexOf(signature)
  expect(start, `${signature} not found in App.tsx`).toBeGreaterThan(-1)
  // Every top-level function in App.tsx is closed by a line containing only
  // "  }" at the component's indentation.
  const end = source.indexOf("\n  }\n", start)
  expect(end, `end of ${signature} not found`).toBeGreaterThan(start)
  return source.slice(start, end)
}

describe("navigating with no workspace loaded", () => {
  const navigate = functionBody(app, "function navigate(screen: ScreenId)")

  it("refuses the screen change instead of setting activeScreen anyway", () => {
    const guard = navigate.indexOf("if (!workspace)")
    const setScreen = navigate.indexOf("setActiveScreen(screen)")

    expect(guard).toBeGreaterThan(-1)
    expect(setScreen).toBeGreaterThan(-1)
    expect(guard).toBeLessThan(setScreen)
  })

  it("says why, rather than swallowing the click", () => {
    expect(navigate).toContain("noWorkspaceNotice()")
    expect(navigate).toContain("toast.info")
  })
})

describe("the manual-review button while a claim is awaiting documents", () => {
  it("is not wired to a handler that cannot navigate", () => {
    const awaiting = app.slice(
      app.indexOf('bootstrap.status === "awaiting-documents"'),
      app.indexOf("onContinue={() => void connectToApi()}")
    )

    expect(awaiting).toContain("<ClientIntakeScreen")
    // `openManualReview` calls `navigate`, which cannot leave this arm.
    expect(awaiting).not.toContain("onOpenManualReview={openManualReview}")
    expect(awaiting).toContain("manualReviewUnavailableNotice()")
  })
})
