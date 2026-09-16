import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { bootstrapClaimWorkspace, claimToOpen } from "./api"

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

function claim(caseReference: string, invoiceCount = 0) {
  return {
    id: `case-${caseReference}`,
    case_reference: caseReference,
    status: "claim_review",
    created_at: "2026-09-16T09:00:00",
    invoice_count: invoiceCount,
  }
}

function errorResponse(code: string, message: string, status: number) {
  return jsonResponse({ detail: { code, message } }, status)
}

/** Answers a sequence of responses for one URL pattern, in order. */
function inSequence(...responses: Array<() => Response>) {
  let index = 0
  return () => responses[Math.min(index++, responses.length - 1)]()
}

/** Captures which URLs were requested, answering each from `routes`. */
function mockFetch(
  routes: Array<[RegExp, () => Response | Promise<Response>]>
) {
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

// The reset wipes every case and creates a fresh one, so the claim named by
// the list call can be gone by the time the workspace call goes out.
describe("a claim that disappears between the two calls", () => {
  it("re-reads the list and opens whatever is there now, without blaming the API", async () => {
    const calls = mockFetch([
      [
        /\/api\/v1\/claims$/,
        inSequence(
          () => jsonResponse([claim("CG-CLIENT-001", 3)]),
          () => jsonResponse([claim("CG-CLIENT-002", 1)])
        ),
      ],
      [
        /CG-CLIENT-001\/workspace/,
        () => errorResponse("NOT_FOUND", "Claim not found", 404),
      ],
      [/CG-CLIENT-002\/workspace/, () => jsonResponse(workspacePayload)],
    ])

    const result = await bootstrapClaimWorkspace(10)

    expect(result.status).toBe("ready")
    expect(result).toMatchObject({ caseReference: "CG-CLIENT-002" })
    // list, 404 workspace, list again, workspace again.
    expect(calls).toHaveLength(4)
  })

  it("reports an empty database when the re-read finds no claims", async () => {
    mockFetch([
      [
        /\/api\/v1\/claims$/,
        inSequence(
          () => jsonResponse([claim("CG-CLIENT-001", 3)]),
          () => jsonResponse([])
        ),
      ],
      [/\/workspace/, () => errorResponse("NOT_FOUND", "Claim not found", 404)],
    ])

    const result = await bootstrapClaimWorkspace(10)

    expect(result).toEqual({ status: "no-claims" })
  })

  it("stops after one retry instead of chasing the list forever", async () => {
    const calls = mockFetch([
      [/\/api\/v1\/claims$/, () => jsonResponse([claim("CG-CLIENT-001", 3)])],
      [/\/workspace/, () => errorResponse("NOT_FOUND", "Claim not found", 404)],
    ])

    const result = await bootstrapClaimWorkspace(10)

    expect(result.status).toBe("workspace-error")
    expect(calls).toHaveLength(4)
  })
})

describe("a 409 that is not 'nothing has been extracted'", () => {
  it("does not claim the case is empty when it holds invoices", async () => {
    mockFetch([
      [/\/api\/v1\/claims$/, () => jsonResponse([claim("CG-CLIENT-001", 5)])],
      [
        /\/workspace/,
        () =>
          errorResponse(
            "WORKSPACE_NOT_READY",
            "The selected invoice does not belong to this claim.",
            409
          ),
      ],
    ])

    const result = await bootstrapClaimWorkspace(10)

    expect(result).toEqual({
      status: "workspace-error",
      caseReference: "CG-CLIENT-001",
      message: "The selected invoice does not belong to this claim.",
    })
  })

  it("accepts a 409 whose detail is a bare string, where `code` is null", async () => {
    mockFetch([
      [/\/api\/v1\/claims$/, () => jsonResponse([claim("CG-CLIENT-001")])],
      [
        /\/workspace/,
        () =>
          jsonResponse({ detail: "The claim has no extracted invoice." }, 409),
      ],
    ])

    const result = await bootstrapClaimWorkspace(10)

    expect(result).toEqual({
      status: "awaiting-documents",
      caseReference: "CG-CLIENT-001",
      message: "The claim has no extracted invoice.",
    })
  })

  it("does not mistake an unrelated 409 code for a claim with no documents", async () => {
    mockFetch([
      [/\/api\/v1\/claims$/, () => jsonResponse([claim("CG-CLIENT-001")])],
      [
        /\/workspace/,
        () => errorResponse("CLAIM_LOCKED", "This claim is locked.", 409),
      ],
    ])

    const result = await bootstrapClaimWorkspace(10)

    expect(result.status).toBe("unavailable")
  })
})

describe("choosing which claim to open", () => {
  it("prefers the newest claim that actually holds an invoice", () => {
    const chosen = claimToOpen([
      claim("CG-CLIENT-003", 0),
      claim("CG-CLIENT-002", 5),
      claim("CG-CLIENT-001", 2),
    ])

    expect(chosen?.case_reference).toBe("CG-CLIENT-002")
  })

  it("falls back to the newest claim when nothing has been uploaded anywhere", () => {
    const chosen = claimToOpen([claim("CG-CLIENT-002"), claim("CG-CLIENT-001")])

    expect(chosen?.case_reference).toBe("CG-CLIENT-002")
  })

  it("has nothing to open when the database is empty", () => {
    expect(claimToOpen([])).toBeNull()
  })

  it("opens reviewed work rather than an empty case created after it", async () => {
    const calls = mockFetch([
      [
        /\/api\/v1\/claims$/,
        () => jsonResponse([claim("CG-CLIENT-002"), claim("CG-CLIENT-001", 5)]),
      ],
      [/\/workspace/, () => jsonResponse(workspacePayload)],
    ])

    const result = await bootstrapClaimWorkspace(10)

    expect(result).toMatchObject({
      status: "ready",
      caseReference: "CG-CLIENT-001",
    })
    expect(calls[1]).toContain("/claims/CG-CLIENT-001/workspace")
  })
})

describe("a malformed claim list", () => {
  it("is reported as an API error, not as an empty database", async () => {
    const calls = mockFetch([[/\/api\/v1\/claims$/, () => jsonResponse({})]])

    const result = await bootstrapClaimWorkspace(10)

    expect(result.status).toBe("unavailable")
    expect(result).toMatchObject({
      message: expect.stringContaining("cannot read"),
    })
    // No workspace is requested off a list that could not be read.
    expect(calls).toHaveLength(1)
  })

  it("does not treat a null body as an empty database either", async () => {
    mockFetch([[/\/api\/v1\/claims$/, () => jsonResponse(null)]])

    const result = await bootstrapClaimWorkspace(10)

    expect(result.status).toBe("unavailable")
  })
})
