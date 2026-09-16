import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { runCaseLinkSweep } from "./document-api"

// `runCaseLinkSweep` used to post to `POST /claims/{ref}/compare`, fired
// silently from the Upload button. On a case that already carries a
// comparison that endpoint runs `reprocess_case`: a new `ProcessingRun`, every
// handler mapping-review decision from the previous run discarded, the LLM
// adjudicator re-run, and `CASE_COMPARISON_COMPLETED` audit events written
// against `pilot.handler` for an action no handler took. Nothing in this
// screen's flow should be able to reach it, so the URL is asserted directly.

const requested: Array<{ url: string; method: string | undefined }> = []

beforeEach(() => {
  requested.length = 0
  vi.stubGlobal("window", {
    setTimeout: globalThis.setTimeout.bind(globalThis),
    clearTimeout: globalThis.clearTimeout.bind(globalThis),
  })
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    requested.push({ url: String(input), method: init?.method })
    return new Response(
      JSON.stringify({
        case_reference: "CG-2026-0048",
        assessments: 2,
        paired: 1,
        unpaired: 1,
        details: [],
      }),
      { status: 200, headers: { "content-type": "application/json" } }
    )
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("the case link sweep calls the sweep endpoint, and nothing else", () => {
  it("posts to the dedicated link-sweep endpoint", async () => {
    await runCaseLinkSweep("CG-2026-0048")

    expect(requested).toHaveLength(1)
    expect(requested[0].method).toBe("POST")
    expect(requested[0].url).toContain(
      "/api/v1/claims/CG-2026-0048/documents/link-sweep"
    )
  })

  it("never touches the comparison endpoint", async () => {
    await runCaseLinkSweep("CG-2026-0048")

    for (const call of requested) {
      expect(call.url).not.toMatch(/\/compare(\?|$)/)
    }
  })

  it("encodes a case reference that needs it", async () => {
    await runCaseLinkSweep("CG/2026 0048")

    expect(requested[0].url).toContain("CG%2F2026%200048")
  })

  it("returns the pairing summary the endpoint actually sends back", async () => {
    // The old return type was a fabricated `{ status: string }`; the endpoint
    // returns the case reference plus `_pairing_summary`, so the screen can
    // say how many estimates ended up linked.
    const summary = await runCaseLinkSweep("CG-2026-0048")

    expect(summary.assessments).toBe(2)
    expect(summary.paired).toBe(1)
    expect(summary.unpaired).toBe(1)
  })
})
