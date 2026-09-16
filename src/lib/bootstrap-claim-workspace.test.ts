import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { bootstrapClaimWorkspace } from "./api"

// api.ts reaches for window.setTimeout inside its fetch timeout helper; the
// test environment is node, so provide the two timer functions it uses.
beforeEach(() => {
  vi.stubGlobal("window", {
    setTimeout: globalThis.setTimeout.bind(globalThis),
    clearTimeout: globalThis.clearTimeout.bind(globalThis),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response
}

function claim(caseReference: string) {
  return {
    id: `case-${caseReference}`,
    case_reference: caseReference,
    status: "claim_review",
    created_at: "2026-09-16T09:00:00",
    invoice_count: 0,
  }
}

/** Captures which URLs were requested, answering each from `routes`. */
function mockFetch(routes: Array<[RegExp, () => Response | Promise<Response>]>) {
  const calls: string[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    calls.push(url)
    for (const [pattern, respond] of routes) {
      if (pattern.test(url)) return respond()
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  return calls
}

const workspacePayload = {
  liability: { status: "PENDING", humanConfirmed: false },
  claim: { id: "CG-CLIENT-001", status: "claim_review" },
  invoice: { id: "invoice-1", number: "343653726836/1~3538" },
  lines: [],
  summary: {},
}

describe("bootstrapClaimWorkspace", () => {
  it("reports the API as unavailable when the claim list cannot be read", async () => {
    mockFetch([[/\/api\/v1\/claims$/, () => jsonResponse({}, 503)]])

    const result = await bootstrapClaimWorkspace(10)

    expect(result.status).toBe("unavailable")
    expect(result).toHaveProperty("message")
  })

  it("reports the API as unavailable when the request itself fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch")
      })
    )

    const result = await bootstrapClaimWorkspace(10)

    expect(result).toEqual({
      status: "unavailable",
      message: "Failed to fetch",
    })
  })

  it("reports no claims when the database is empty, without inventing one", async () => {
    const calls = mockFetch([[/\/api\/v1\/claims$/, () => jsonResponse([])]])

    const result = await bootstrapClaimWorkspace(10)

    expect(result).toEqual({ status: "no-claims" })
    // Nothing else is requested; in particular no workspace is fetched for a
    // guessed case reference.
    expect(calls).toHaveLength(1)
  })

  it("opens the most recently created claim rather than a hard-coded reference", async () => {
    const calls = mockFetch([
      [
        /\/api\/v1\/claims$/,
        () => jsonResponse([claim("CG-CLIENT-002"), claim("CG-CLIENT-001")]),
      ],
      [/\/workspace/, () => jsonResponse(workspacePayload)],
    ])

    const result = await bootstrapClaimWorkspace(10)

    expect(result.status).toBe("ready")
    expect(result).toMatchObject({ caseReference: "CG-CLIENT-002" })
    expect(calls[1]).toContain("/claims/CG-CLIENT-002/workspace")
    expect(calls.join(" ")).not.toContain("CG-2026-0048")
  })

  it("treats a claim with nothing extracted as awaiting documents, not an outage", async () => {
    mockFetch([
      [/\/api\/v1\/claims$/, () => jsonResponse([claim("CG-CLIENT-001")])],
      [
        /\/workspace/,
        () =>
          jsonResponse(
            {
              detail: {
                code: "WORKSPACE_NOT_READY",
                message: "The claim has no extracted invoice.",
              },
            },
            409
          ),
      ],
    ])

    const result = await bootstrapClaimWorkspace(10)

    expect(result).toEqual({
      status: "awaiting-documents",
      caseReference: "CG-CLIENT-001",
      message: "The claim has no extracted invoice.",
    })
  })

  it("still reports an outage when the workspace fails for any other reason", async () => {
    mockFetch([
      [/\/api\/v1\/claims$/, () => jsonResponse([claim("CG-CLIENT-001")])],
      [/\/workspace/, () => jsonResponse({}, 500)],
    ])

    const result = await bootstrapClaimWorkspace(10)

    expect(result.status).toBe("unavailable")
  })
})
