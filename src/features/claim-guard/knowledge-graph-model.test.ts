import { describe, expect, it } from "vitest"
import type { ChallengeKnowledgeGraphPayload } from "@/lib/api"
import {
  buildChallengeNetwork,
  demoGraphPayload,
  graphNodeId,
  type GraphEvidence,
} from "./knowledge-graph-model"

function payload(
  rows: Array<Partial<GraphEvidence>>
): ChallengeKnowledgeGraphPayload {
  return {
    ...demoGraphPayload,
    edges: rows.map((row, index) => ({
      ...demoGraphPayload.edges[0],
      id: `edge-${index}`,
      itemId: row.itemId ?? "spark",
      item: row.item ?? "Spark plugs",
      evidence: [
        {
          ...demoGraphPayload.edges[0].evidence[0],
          lineId: `line-${index}`,
          invoiceId: "invoice-1",
          invoiceNumber: "9510",
          repairer: "Repairer A",
          challengeAmount: 10,
          ...row,
        },
      ],
    })),
  }
}

describe("challenge knowledge network", () => {
  it("creates exactly three node types, with only actual repairer–invoice–part links", () => {
    const graph = buildChallengeNetwork(
      payload([
        { invoiceId: "one", itemId: "spark" },
        { invoiceId: "two", itemId: "oil", repairer: "Repairer B" },
      ])
    )
    expect(graph.nodes).toHaveLength(6)
    expect(graph.edges).toHaveLength(6)
    expect(graph.edges.map((edge) => [edge.source, edge.target])).toEqual(
      expect.arrayContaining([
        [graphNodeId("repairer", "Repairer A"), graphNodeId("invoice", "one")],
        [graphNodeId("invoice", "one"), graphNodeId("part", "spark")],
        [graphNodeId("part", "spark"), graphNodeId("repairer", "Repairer A")],
      ])
    )
    expect(
      graph.edges.some(
        (edge) =>
          edge.source === graphNodeId("invoice", "two") &&
          edge.target === graphNodeId("part", "spark")
      )
    ).toBe(false)
  })

  it("aggregates repeated part lines without duplicate nodes, edges or money", () => {
    const graph = buildChallengeNetwork(
      payload([{ challengeAmount: 10 }, { challengeAmount: 20 }])
    )
    expect(graph.nodes).toHaveLength(3)
    expect(graph.edges).toHaveLength(3)
    expect(
      graph.nodes.every(
        (node) => node.challengeCount === 2 && node.totalChallenge === 30
      )
    ).toBe(true)
    expect(
      graph.edges.every(
        (edge) => edge.evidence.length === 2 && edge.totalChallenge === 30
      )
    ).toBe(true)
    expect(graph.totalChallenge).toBe(30)
  })

  it("connects one challenged part directly to every repairer that charged it", () => {
    const graph = buildChallengeNetwork(
      payload([
        {
          invoiceId: "one",
          itemId: "spark",
          repairer: "Repairer A",
          challengeAmount: 10,
        },
        {
          invoiceId: "two",
          itemId: "spark",
          repairer: "Repairer B",
          challengeAmount: 20,
        },
      ])
    )
    const partId = graphNodeId("part", "spark")
    const repairerLinks = graph.edges.filter(
      (edge) => edge.label === "CHARGED_BY" && edge.source === partId
    )

    expect(repairerLinks).toHaveLength(2)
    expect(repairerLinks.map((edge) => edge.target)).toEqual(
      expect.arrayContaining([
        graphNodeId("repairer", "Repairer A"),
        graphNodeId("repairer", "Repairer B"),
      ])
    )
    expect(repairerLinks.map((edge) => edge.totalChallenge).sort()).toEqual([
      10, 20,
    ])
  })

  it("keeps distinct invoices with the same displayed invoice number separate", () => {
    const graph = buildChallengeNetwork(
      payload([{ invoiceId: "a" }, { invoiceId: "b" }])
    )
    expect(graph.nodes.filter((node) => node.kind === "invoice")).toHaveLength(
      2
    )
    expect(graph.availableCounts.invoice).toBe(2)
  })

  it("deduplicates the same invoice line in repeated payload edges", () => {
    const graph = buildChallengeNetwork(
      payload([{ lineId: "same" }, { lineId: "same" }])
    )
    expect(graph.evidence).toHaveLength(1)
    expect(graph.totalChallenge).toBe(10)
  })

  it("excludes rejected, zero, negative, invalid and unidentified lines", () => {
    const graph = buildChallengeNetwork(
      payload([
        { status: "REJECTED" },
        { challengeAmount: 0 },
        { challengeAmount: -4 },
        { challengeAmount: NaN },
        { invoiceId: "" },
        { lineId: "" },
        { status: "approved" },
      ])
    )
    expect(graph.evidence).toHaveLength(1)
    expect(graph.totalChallenge).toBe(10)
  })

  it("ranks and caps each category independently, preserving full case totals", () => {
    const graph = buildChallengeNetwork(
      payload(
        Array.from({ length: 12 }, (_, i) => ({
          invoiceId: `invoice-${i}`,
          repairer: `repairer-${i}`,
          itemId: `part-${i}`,
          challengeAmount: i + 1,
        }))
      )
    )
    for (const kind of ["repairer", "invoice", "part"] as const) {
      const nodes = graph.nodes.filter((node) => node.kind === kind)
      expect(nodes).toHaveLength(10)
      expect(nodes.map((node) => node.totalChallenge)).toEqual([
        12, 11, 10, 9, 8, 7, 6, 5, 4, 3,
      ])
      expect(graph.availableCounts[kind]).toBe(12)
    }
    expect(graph.totalChallenge).toBe(78)
    const ids = new Set(graph.nodes.map((node) => node.id))
    expect(
      graph.edges.every((edge) => ids.has(edge.source) && ids.has(edge.target))
    ).toBe(true)
  })

  it("ranks parts across all repairers, not only visible repairers", () => {
    const graph = buildChallengeNetwork(
      payload([
        { repairer: "A", itemId: "a", invoiceId: "1", challengeAmount: 100 },
        { repairer: "B", itemId: "b", invoiceId: "2", challengeAmount: 60 },
        { repairer: "C", itemId: "b", invoiceId: "3", challengeAmount: 60 },
      ]),
      1
    )
    expect(graph.nodes.find((node) => node.kind === "part")?.id).toBe(
      graphNodeId("part", "b")
    )
    expect(
      graph.nodes.find((node) => node.kind === "part")?.evidence
    ).toHaveLength(2)
    expect(graph.edges).toHaveLength(1) // No invented link to the unrelated top invoice.
  })

  it("sorts ties deterministically without changing its input", () => {
    const source = payload([
      { repairer: "Z" },
      { repairer: "A", invoiceId: "second" },
    ])
    const original = JSON.stringify(source)
    const first = buildChallengeNetwork(source)
    expect(
      first.nodes
        .filter((node) => node.kind === "repairer")
        .map((node) => node.label)
    ).toEqual(["A", "Z"])
    expect(
      buildChallengeNetwork({ ...source, edges: [...source.edges].reverse() })
    ).toEqual(first)
    expect(JSON.stringify(source)).toBe(original)
  })

  it("rounds totals to pence and provides an honest empty state", () => {
    expect(
      buildChallengeNetwork(
        payload([{ challengeAmount: 0.1 }, { challengeAmount: 0.2 }])
      ).totalChallenge
    ).toBe(0.3)
    const empty = buildChallengeNetwork(payload([]))
    expect(empty.nodes).toEqual([])
    expect(empty.edges).toEqual([])
    expect(empty.totalChallenge).toBe(0)
  })

  it("keeps prices and provenance attached to the correct selected entity", () => {
    const graph = buildChallengeNetwork(
      payload([
        {
          invoiceId: "one",
          itemId: "spark",
          billedPrice: 100,
          supportedPrice: 60,
          challengeAmount: 40,
          historicalClaimsP90: 60,
        },
        { invoiceId: "two", itemId: "oil", challengeAmount: 20 },
      ])
    )
    const spark = graph.nodes.find(
      (node) => node.id === graphNodeId("part", "spark")
    )!
    expect(spark.evidence).toHaveLength(1)
    expect(spark.evidence[0]).toMatchObject({
      invoiceId: "one",
      billedPrice: 100,
      supportedPrice: 60,
      historicalClaimsP90: 60,
    })
  })
})
