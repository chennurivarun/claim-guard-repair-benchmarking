import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { fetchClaimExtracts } from "@/lib/api"
import {
  BENCHMARK_SOURCES,
  draftChallengeEmail,
  fetchBenchmarkAnalysis,
  fetchSourceBenchmarks,
} from "./benchmark-api"
import { approveCaseMapping, fetchCaseMapping } from "./document-api"

// Per-source scoping is only real if the right `intake_group` / `source`
// reaches the server: a screen headed "EXL/ In house Benchmark invoices" that fetched
// unscoped would show third-party rows under an Aviva heading, and nothing
// on the page could tell. So the requests themselves are asserted.

const requested: Array<{ url: string; method?: string; body?: string }> = []

beforeEach(() => {
  requested.length = 0
  vi.stubGlobal("window", {
    setTimeout: globalThis.setTimeout.bind(globalThis),
    clearTimeout: globalThis.clearTimeout.bind(globalThis),
  })
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    requested.push({
      url: String(input),
      method: init?.method,
      body: typeof init?.body === "string" ? init.body : undefined,
    })
    return new Response("{}", {
      status: 200,
      headers: { "content-type": "application/json" },
    })
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("the two benchmark sources are the two existing upload buckets (D1)", () => {
  it("maps third party to historical_claim and In-house to in_house", () => {
    expect(BENCHMARK_SOURCES.third_party.intakeGroup).toBe("historical_claim")
    expect(BENCHMARK_SOURCES.aviva_dlg.intakeGroup).toBe("in_house")
    expect(BENCHMARK_SOURCES.third_party.label).toBe(
      "Insurer Third Party invoices"
    )
    expect(BENCHMARK_SOURCES.aviva_dlg.label).toBe("EXL/ In house Benchmark invoices")
  })
})

describe("benchmark computation asks for one source", () => {
  it("sends source=third_party", async () => {
    await fetchSourceBenchmarks("CG-2026-0048", "third_party")

    expect(requested[0].url).toContain(
      "/api/v1/claims/CG-2026-0048/benchmarks?source=third_party"
    )
  })

  it("sends source=aviva_dlg", async () => {
    await fetchSourceBenchmarks("CG-2026-0048", "aviva_dlg")

    expect(requested[0].url).toContain("/benchmarks?source=aviva_dlg")
  })
})

describe("benchmark analysis", () => {
  it("lets the server pick the most recent live invoice when none is chosen", async () => {
    await fetchBenchmarkAnalysis("CG-2026-0048")

    expect(requested[0].url).toMatch(
      /\/api\/v1\/claims\/CG-2026-0048\/benchmark-analysis$/
    )
  })

  it("names the chosen invoice", async () => {
    await fetchBenchmarkAnalysis("CG-2026-0048", "live 2")

    expect(requested[0].url).toContain("/benchmark-analysis?invoice_id=live+2")
  })
})

describe("the challenge email is a draft request", () => {
  it("posts the invoice and the selected lines, nothing else", async () => {
    await draftChallengeEmail("CG-2026-0048", {
      invoiceId: "live-1",
      lineIds: ["inv-high", "ea-medium"],
    })

    expect(requested[0].method).toBe("POST")
    expect(requested[0].url).toContain("/api/v1/claims/CG-2026-0048/challenge-email")
    expect(JSON.parse(requested[0].body ?? "{}")).toEqual({
      invoice_id: "live-1",
      line_ids: ["inv-high", "ea-medium"],
    })
  })

  it("passes a recipient name when one is given", async () => {
    await draftChallengeEmail("CG-2026-0048", {
      invoiceId: "live-1",
      lineIds: ["inv-high"],
      recipient: "Acme Repairs",
    })

    expect(JSON.parse(requested[0].body ?? "{}").recipient).toBe("Acme Repairs")
  })
})

describe("mapping and extracts are scoped by intake group", () => {
  it("reads the mapping for one group", async () => {
    await fetchCaseMapping("CG-2026-0048", "in_house")

    expect(requested[0].url).toContain(
      "/api/v1/claims/CG-2026-0048/document-mapping?intake_group=in_house"
    )
  })

  it("still reads the whole claim's mapping when no group is given", async () => {
    await fetchCaseMapping("CG-2026-0048")

    expect(requested[0].url).toMatch(/\/document-mapping$/)
  })

  it("approves one group, so approving third party does not approve In-house", async () => {
    await approveCaseMapping("CG-2026-0048", "pilot.handler", "historical_claim")

    expect(JSON.parse(requested[0].body ?? "{}")).toEqual({
      actor: "pilot.handler",
      intake_group: "historical_claim",
    })
  })

  it("approves without a group exactly as before", async () => {
    await approveCaseMapping("CG-2026-0048", "pilot.handler")

    expect(JSON.parse(requested[0].body ?? "{}")).toEqual({
      actor: "pilot.handler",
    })
  })

  it("reads the extracts for one group", async () => {
    await fetchClaimExtracts("CG-2026-0048", "live")

    expect(requested[0].url).toContain(
      "/api/v1/claims/CG-2026-0048/extracts?intake_group=live"
    )
  })

  it("still reads every extract when no group is given", async () => {
    await fetchClaimExtracts("CG-2026-0048")

    expect(requested[0].url).toMatch(/\/extracts$/)
  })
})
