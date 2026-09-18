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

  // Neha's nine screens act on the claim reference alone. A freshly set-up or
  // reset claim has a reference but no workspace, and her flow starts by
  // uploading into it, so those screens -- and only those -- may be opened
  // before a workspace exists.
  it("lets only the claim-scoped screens through, and only with a claim", () => {
    const guard = navigate.indexOf("if (!workspace)")
    const exemption = navigate.indexOf("claimReference && screenScope(screen)")
    const firstSet = navigate.indexOf("setActiveScreen(screen)")

    expect(exemption).toBeGreaterThan(guard)
    expect(exemption).toBeLessThan(firstSet)
    // Everything else still falls through to the spoken refusal.
    expect(navigate.indexOf("noWorkspaceNotice()")).toBeGreaterThan(exemption)
  })
})

describe("a claim awaiting its first documents", () => {
  const awaiting = app.slice(
    app.indexOf('bootstrap.status === "awaiting-documents"'),
    app.indexOf("onContinue={() => void connectToApi()}")
  )

  it("renders Neha's screens, so upload into either source is possible", () => {
    expect(awaiting).toContain("{scope ? (")
    expect(awaiting).toContain("screen")
  })

  it("builds those screens from the claim reference, not the workspace", () => {
    const block = app.slice(
      app.indexOf("if (scope && claimReference)"),
      app.indexOf("} else if (workspace)")
    )
    expect(block.length).toBeGreaterThan(0)
    expect(block).toContain("caseReference={claimReference}")
    expect(block).not.toContain("workspace.claim.id")
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

// An empty database (no `claimguard-setup` in this folder, or a reset with
// `--no-new-case`) used to be a dead end: every upload screen needs a claim to
// upload into, and the panel offered only "Check again".
describe("an empty database", () => {
  const start = functionBody(app, "async function startFirstClaim()")

  it("offers a working way to start, wired from the no-claims panel", () => {
    const arm = app.slice(
      app.indexOf('bootstrap.status === "no-claims"'),
      app.indexOf('bootstrap.status === "workspace-error"')
    )
    expect(arm).toContain("onStart={() => void startFirstClaim()}")
  })

  it("starts the claim, reopens it, then lands on the Third party upload screen", () => {
    const create = start.indexOf("startClaimOnEmptyDatabase()")
    const reopen = start.indexOf("connectToApi()")
    const land = start.indexOf('setActiveScreen("tp-upload")')

    expect(create).toBeGreaterThan(-1)
    expect(reopen).toBeGreaterThan(create)
    expect(land).toBeGreaterThan(reopen)
  })

  it("never starts twice from a double click", () => {
    const guard = start.indexOf("if (claimStarting) return")
    expect(guard).toBeGreaterThan(-1)
    expect(guard).toBeLessThan(start.indexOf("startClaimOnEmptyDatabase()"))
  })
})
