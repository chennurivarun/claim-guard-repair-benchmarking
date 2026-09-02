import type { ChallengeKnowledgeGraphPayload } from "@/lib/api"

export type GraphNodeKind = "repairer" | "invoice" | "part"
export type GraphEvidence =
  ChallengeKnowledgeGraphPayload["edges"][number]["evidence"][number] & {
    itemId: string
    item: string
  }
export type ChallengeGraphNode = {
  id: string
  kind: GraphNodeKind
  label: string
  challengeCount: number
  invoiceCount: number
  totalChallenge: number
  evidence: GraphEvidence[]
}
export type ChallengeGraphEdge = {
  id: string
  source: string
  target: string
  label: "ISSUED" | "CHALLENGED_PART"
  totalChallenge: number
  evidence: GraphEvidence[]
}

export const graphKinds: GraphNodeKind[] = ["repairer", "invoice", "part"]
export const graphKindLabels = {
  repairer: "Repairers",
  invoice: "Invoices",
  part: "Parts",
}
export const graphColors = {
  repairer: "#2563eb",
  invoice: "#fdba74",
  part: "#a5e4f4",
}

export function graphNodeId(kind: GraphNodeKind, key: string) {
  return JSON.stringify([kind, key])
}

export function evidenceKey(row: GraphEvidence) {
  return JSON.stringify([row.invoiceId, row.lineId])
}

const moneyTotal = (rows: GraphEvidence[]) =>
  Math.round(
    rows.reduce((total, row) => total + row.challengeAmount, 0) * 100
  ) / 100

/** Rank each type independently across all qualifying lines, before limiting the view. */
export function buildChallengeNetwork(
  payload: ChallengeKnowledgeGraphPayload,
  limit = 10
) {
  const evidenceMap = new Map<string, GraphEvidence>()
  for (const edge of payload.edges) {
    for (const row of edge.evidence) {
      if (
        !row.invoiceId ||
        !row.lineId ||
        !Number.isFinite(row.challengeAmount) ||
        row.challengeAmount <= 0 ||
        row.status.toLowerCase() === "rejected"
      )
        continue
      const evidence = { ...row, itemId: edge.itemId, item: edge.item }
      evidenceMap.set(evidenceKey(evidence), evidence)
    }
  }
  const evidence = [...evidenceMap.values()].sort(
    (a, b) =>
      b.challengeAmount - a.challengeAmount ||
      evidenceKey(a).localeCompare(evidenceKey(b))
  )
  const nodeMap = new Map<string, ChallengeGraphNode>()
  for (const row of evidence) {
    const entities: Array<[GraphNodeKind, string, string]> = [
      ["repairer", row.repairer, row.repairer || "Unknown repairer"],
      ["invoice", row.invoiceId, row.invoiceNumber || row.invoiceId],
      ["part", row.itemId, row.item],
    ]
    for (const [kind, key, label] of entities) {
      const id = graphNodeId(kind, key)
      const node = nodeMap.get(id) ?? {
        id,
        kind,
        label,
        challengeCount: 0,
        invoiceCount: 0,
        totalChallenge: 0,
        evidence: [],
      }
      node.evidence.push(row)
      nodeMap.set(id, node)
    }
  }
  const ranked = [...nodeMap.values()]
    .map((node) => ({
      ...node,
      challengeCount: node.evidence.length,
      invoiceCount: new Set(node.evidence.map((row) => row.invoiceId)).size,
      totalChallenge: moneyTotal(node.evidence),
    }))
    .sort(
      (a, b) =>
        b.totalChallenge - a.totalChallenge ||
        b.challengeCount - a.challengeCount ||
        a.label.localeCompare(b.label) ||
        a.id.localeCompare(b.id)
    )
  const nodes = graphKinds.flatMap((kind) =>
    ranked
      .filter((node) => node.kind === kind)
      .slice(0, Math.max(0, Math.floor(limit)))
  )
  const shownIds = new Set(nodes.map((node) => node.id))
  const edgeMap = new Map<string, ChallengeGraphEdge>()
  for (const row of evidence) {
    const invoice = graphNodeId("invoice", row.invoiceId)
    const relationships: Array<[string, string, ChallengeGraphEdge["label"]]> =
      [
        [graphNodeId("repairer", row.repairer), invoice, "ISSUED"],
        [invoice, graphNodeId("part", row.itemId), "CHALLENGED_PART"],
      ]
    for (const [source, target, label] of relationships) {
      if (!shownIds.has(source) || !shownIds.has(target)) continue
      const id = JSON.stringify([label, source, target])
      const edge = edgeMap.get(id) ?? {
        id,
        source,
        target,
        label,
        totalChallenge: 0,
        evidence: [],
      }
      edge.evidence.push(row)
      edgeMap.set(id, edge)
    }
  }
  const edges = [...edgeMap.values()].map((edge) => ({
    ...edge,
    totalChallenge: moneyTotal(edge.evidence),
  }))
  return {
    nodes,
    edges,
    evidence,
    availableCounts: Object.fromEntries(
      graphKinds.map((kind) => [
        kind,
        ranked.filter((node) => node.kind === kind).length,
      ])
    ) as Record<GraphNodeKind, number>,
    totalChallenge: moneyTotal(evidence),
  }
}

export type ChallengeNetwork = ReturnType<typeof buildChallengeNetwork>

// Explicit offline sample, never substituted when live data fails to load.
export const demoGraphPayload: ChallengeKnowledgeGraphPayload = {
  caseReference: "demo",
  storage: "relational-fallback",
  summary: {
    mostChallengedRepairer: null,
    mostChallengedItem: null,
    challengedInvoiceCount: 2,
    potentialReduction: 490,
  },
  repairers: [],
  items: [],
  edges: [
    {
      id: "demo-bumper",
      repairer: "Pilot Repair Network",
      itemId: "PART-BUMPER",
      item: "Front bumper repair",
      invoiceCount: 2,
      challengeCount: 2,
      totalChallenge: 490,
      maximumChallenge: 260,
      evidence: [
        {
          lineId: "demo-line-7",
          invoiceId: "demo-invoice-7",
          invoiceNumber: "INV-007",
          repairer: "Pilot Repair Network",
          description: "Front bumper repair",
          billedPrice: 1480,
          supportedPrice: 1220,
          challengeAmount: 260,
          inHouseP90: null,
          historicalClaimsP90: 1220,
          externalReferencePrice: null,
          status: "review",
        },
        {
          lineId: "demo-line-8",
          invoiceId: "demo-invoice-8",
          invoiceNumber: "INV-008",
          repairer: "Pilot Repair Network",
          description: "Repair front bumper",
          billedPrice: 1445,
          supportedPrice: 1215,
          challengeAmount: 230,
          inHouseP90: null,
          historicalClaimsP90: 1215,
          externalReferencePrice: null,
          status: "review",
        },
      ],
    },
  ],
}
