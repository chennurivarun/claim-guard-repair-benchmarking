import { lazy, Suspense, useEffect, useMemo, useState } from "react"
import { ArrowLeftIcon, NetworkIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  fetchChallengeKnowledgeGraph,
  type ChallengeKnowledgeGraphPayload,
} from "@/lib/api"
import {
  buildChallengeNetwork,
  demoGraphPayload,
  evidenceKey,
  graphColors,
  graphKindLabels,
  graphKinds,
  type ChallengeNetwork,
  type GraphEvidence,
} from "./knowledge-graph-model"
import { DataCard, ScreenHeading } from "./shared"

// The graph library is only downloaded when a graph is actually displayed.
const KnowledgeGraphCanvas = lazy(() => import("./knowledge-graph-canvas"))
const money = (value: number | null) =>
  value == null
    ? "—"
    : value.toLocaleString("en-GB", { style: "currency", currency: "GBP" })

export function KnowledgeGraphScreen({
  apiMode,
  caseReference,
  challengeThreshold,
  onBack,
}: {
  apiMode: "api" | "demo"
  caseReference: string
  challengeThreshold: number
  onBack: () => void
}) {
  const [retry, setRetry] = useState(0)
  const requestKey = JSON.stringify([
    apiMode,
    caseReference,
    challengeThreshold,
    retry,
  ])
  const [result, setResult] = useState<{
    key: string
    payload: ChallengeKnowledgeGraphPayload | null
    error: boolean
  } | null>(null)
  useEffect(() => {
    if (apiMode === "demo") return
    let cancelled = false
    void fetchChallengeKnowledgeGraph(caseReference, challengeThreshold).then(
      (payload) => {
        if (!cancelled) setResult({ key: requestKey, payload, error: false })
      },
      () => {
        if (!cancelled)
          setResult({ key: requestKey, payload: null, error: true })
      }
    )
    return () => {
      cancelled = true
    }
  }, [apiMode, caseReference, challengeThreshold, requestKey])
  const currentResult = result?.key === requestKey ? result : null
  const payload = apiMode === "demo" ? demoGraphPayload : currentResult?.payload

  return (
    <div className="flex flex-col gap-6">
      <ScreenHeading
        title="Repairer knowledge graph"
        description="Explore how repairers, invoices and parts connect through actual positive price challenges."
        action={
          <Button variant="outline" onClick={onBack}>
            <ArrowLeftIcon aria-hidden />
            Back to benchmarks
          </Button>
        }
      />
      {apiMode === "demo" ? (
        <Alert>
          <AlertTitle>Demo graph</AlertTitle>
          <AlertDescription>
            Illustrative sample only. Uploaded-invoice results appear when the
            API is connected.
          </AlertDescription>
        </Alert>
      ) : null}
      {currentResult?.error ? (
        <Alert variant="destructive">
          <NetworkIcon aria-hidden />
          <AlertTitle>Knowledge graph unavailable</AlertTitle>
          <AlertDescription>
            The live challenge data could not be loaded. No sample data has been
            substituted.
            <Button
              variant="outline"
              onClick={() => setRetry((value) => value + 1)}
            >
              Retry graph
            </Button>
          </AlertDescription>
        </Alert>
      ) : payload ? (
        <GraphExplorer key={requestKey} payload={payload} />
      ) : (
        <p
          role="status"
          className="rounded-lg border p-8 text-muted-foreground"
        >
          Loading uploaded-invoice relationships…
        </p>
      )}
    </div>
  )
}

function GraphExplorer({
  payload,
}: {
  payload: ChallengeKnowledgeGraphPayload
}) {
  const graph = useMemo(() => buildChallengeNetwork(payload), [payload])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [view, setView] = useState<"graph" | "table">("graph")
  const selectedNode = graph.nodes.find((node) => node.id === selectedId)
  const selectedEdge = graph.edges.find((edge) => edge.id === selectedId)
  const nodeNames = new Map(graph.nodes.map((node) => [node.id, node.label]))
  const selected = selectedNode ?? selectedEdge
  const selectedTitle =
    selectedNode?.label ??
    (selectedEdge
      ? nodeNames.get(selectedEdge.source) +
        " → " +
        nodeNames.get(selectedEdge.target)
      : "Select a node or relationship")
  const rows = selected?.evidence ?? []
  const connectedCount = selectedNode
    ? graph.edges.filter(
        (edge) =>
          edge.source === selectedNode.id || edge.target === selectedNode.id
      ).length
    : 0
  const topRepairer = graph.nodes.find((node) => node.kind === "repairer")
  const topPart = graph.nodes.find((node) => node.kind === "part")

  if (!graph.nodes.length)
    return (
      <Alert>
        <NetworkIcon aria-hidden />
        <AlertTitle>No challenge relationships at this setting</AlertTitle>
        <AlertDescription>
          The graph appears when invoice lines have positive, non-rejected
          challenges that pass the current review gates.
        </AlertDescription>
      </Alert>
    )

  return (
    <>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <DataCard
          title="Most challenged repairer"
          description="By total challenge amount"
        >
          <p className="font-semibold">{topRepairer?.label ?? "—"}</p>
          <p className="text-sm text-muted-foreground">
            {money(topRepairer?.totalChallenge ?? 0)} ·{" "}
            {topRepairer?.invoiceCount} invoices
          </p>
        </DataCard>
        <DataCard
          title="Most challenged part"
          description="By total challenge amount, across all repairers"
        >
          <p className="font-semibold">{topPart?.label ?? "—"}</p>
          <p className="text-sm text-muted-foreground">
            {money(topPart?.totalChallenge ?? 0)} · {topPart?.invoiceCount}{" "}
            invoices
          </p>
        </DataCard>
        <DataCard
          title="Challenged invoices"
          description="All qualifying invoices, before the top-10 limit"
        >
          <p className="text-2xl font-semibold tabular-nums">
            {graph.availableCounts.invoice}
          </p>
        </DataCard>
        <DataCard
          title="Potential reduction"
          description="All qualifying lines, counted once"
        >
          <p className="text-2xl font-semibold tabular-nums">
            {money(graph.totalChallenge)}
          </p>
        </DataCard>
      </div>

      <section
        className="overflow-hidden rounded-xl border"
        aria-label="Challenge network explorer"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-card px-4 py-3">
          <div>
            <h2 className="font-semibold">
              Repairer → Invoice → Challenged part · Part → Repairer
            </h2>
            <p className="text-xs text-muted-foreground">
              Top 10 of each type by total challenge amount · Actual challenge
              connections
            </p>
          </div>
          <div className="flex gap-1" role="group" aria-label="Network view">
            <Button
              size="sm"
              variant={view === "graph" ? "secondary" : "ghost"}
              aria-pressed={view === "graph"}
              onClick={() => setView("graph")}
            >
              Graph
            </Button>
            <Button
              size="sm"
              variant={view === "table" ? "secondary" : "ghost"}
              aria-pressed={view === "table"}
              onClick={() => setView("table")}
            >
              Table
            </Button>
          </div>
        </div>
        <div className="grid min-w-0 xl:grid-cols-[minmax(0,1fr)_300px]">
          {view === "graph" ? (
            <Suspense
              fallback={
                <p role="status" className="min-h-[520px] p-8">
                  Loading interactive graph…
                </p>
              }
            >
              <KnowledgeGraphCanvas
                graph={graph}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            </Suspense>
          ) : (
            <NetworkTable
              graph={graph}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          )}
          <aside
            className="min-w-0 space-y-5 border-t bg-card p-5 xl:border-t-0 xl:border-l"
            aria-label="Results overview"
          >
            <div>
              <h3 className="font-semibold">Results overview</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                {graph.nodes.length} nodes · {graph.edges.length} relationships
                shown
              </p>
            </div>
            <div className="space-y-2">
              <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                Node types
              </p>
              {graphKinds.map((kind) => (
                <div
                  key={kind}
                  className="flex items-center justify-between gap-2 text-sm"
                >
                  <Badge
                    style={{
                      backgroundColor: graphColors[kind],
                      color: kind === "repairer" ? "white" : "#102033",
                    }}
                  >
                    {graphKindLabels[kind]}
                  </Badge>
                  <span className="text-xs tabular-nums">
                    {graph.nodes.filter((node) => node.kind === kind).length} of{" "}
                    {graph.availableCounts[kind]}
                  </span>
                </div>
              ))}
            </div>
            <div className="space-y-2 text-xs">
              <p className="font-medium tracking-wide text-muted-foreground uppercase">
                Relationships
              </p>
              <p>
                ISSUED{" "}
                <span className="float-right">
                  {graph.edges.filter((edge) => edge.label === "ISSUED").length}
                </span>
              </p>
              <p>
                CHALLENGED_PART{" "}
                <span className="float-right">
                  {
                    graph.edges.filter(
                      (edge) => edge.label === "CHALLENGED_PART"
                    ).length
                  }
                </span>
              </p>
              <p>
                CHARGED_BY{" "}
                <span className="float-right">
                  {
                    graph.edges.filter(
                      (edge) => edge.label === "CHARGED_BY"
                    ).length
                  }
                </span>
              </p>
              <p className="pt-1 leading-relaxed text-muted-foreground">
                Each type is ranked independently. Links appear only when both
                endpoints are in the top 10. A node can have connections outside
                this view.
              </p>
            </div>
            <div className="space-y-2 border-t pt-4">
              <label
                htmlFor="graph-node-selection"
                className="text-sm font-medium"
              >
                Inspect a node
              </label>
              <select
                id="graph-node-selection"
                className="h-10 w-full min-w-0 rounded-md border bg-background px-2 text-sm"
                value={selectedNode?.id ?? ""}
                onChange={(event) => setSelectedId(event.target.value || null)}
              >
                <option value="">Select a node…</option>
                {graphKinds.map((kind) => (
                  <optgroup key={kind} label={graphKindLabels[kind]}>
                    {graph.nodes
                      .filter((node) => node.kind === kind)
                      .map((node) => (
                        <option key={node.id} value={node.id}>
                          {node.label}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </select>
              <div aria-live="polite" className="space-y-2 pt-2">
                <h4 className="text-sm font-semibold break-words">
                  {selectedTitle}
                </h4>
                {selected ? (
                  <>
                    <p className="text-xl font-semibold tabular-nums">
                      {money(selected.totalChallenge)}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {rows.length} challenged{" "}
                      {rows.length === 1 ? "line" : "lines"} ·{" "}
                      {new Set(rows.map((row) => row.invoiceId)).size}{" "}
                      {new Set(rows.map((row) => row.invoiceId)).size === 1
                        ? "invoice"
                        : "invoices"}
                    </p>
                    {selectedNode ? (
                      <p className="text-xs text-muted-foreground">
                        {connectedCount} visible connections. Details below
                        include all qualifying lines for this node, including
                        connections outside the top 10.
                      </p>
                    ) : null}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedId(null)}
                    >
                      Clear selection
                    </Button>
                  </>
                ) : (
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    Click any circle or arrow to highlight its connections and
                    inspect the exact invoice lines below. You can also use this
                    selector or Table view.
                  </p>
                )}
              </div>
            </div>
          </aside>
        </div>
      </section>
      {selected ? (
        <DataCard
          title={"Challenge evidence: " + selectedTitle}
          description="Current challenge results for the selected node or connection. Prices are net of VAT; no new benchmark calculation is performed by this graph."
        >
          <EvidenceTable rows={rows} />
        </DataCard>
      ) : null}
    </>
  )
}

function NetworkTable({
  graph,
  selectedId,
  onSelect,
}: {
  graph: ChallengeNetwork
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const names = new Map(graph.nodes.map((node) => [node.id, node.label]))
  return (
    <div className="max-h-[650px] min-w-0 overflow-auto p-4">
      <table className="w-full text-left text-sm">
        <caption className="mb-3 text-left font-medium">
          Ranked nodes · Select a name to inspect
        </caption>
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th className="p-2">Type</th>
            <th className="p-2">Name / number</th>
            <th className="p-2 text-right">Lines</th>
            <th className="p-2 text-right">Challenge amount</th>
          </tr>
        </thead>
        <tbody>
          {graph.nodes.map((node) => (
            <tr
              key={node.id}
              className={
                selectedId === node.id ? "border-b bg-accent" : "border-b"
              }
            >
              <td className="p-2 capitalize">{node.kind}</td>
              <td className="p-2">
                <button
                  className="text-left underline underline-offset-4"
                  onClick={() => onSelect(node.id)}
                >
                  {node.label}
                </button>
              </td>
              <td className="p-2 text-right tabular-nums">
                {node.challengeCount}
              </td>
              <td className="p-2 text-right whitespace-nowrap tabular-nums">
                {money(node.totalChallenge)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <table className="mt-6 w-full text-left text-sm">
        <caption className="mb-3 text-left font-medium">
          Visible relationships
        </caption>
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th className="p-2">From → To</th>
            <th className="p-2">Relationship</th>
            <th className="p-2 text-right">Challenge amount</th>
          </tr>
        </thead>
        <tbody>
          {graph.edges.map((edge) => (
            <tr
              key={edge.id}
              className={
                selectedId === edge.id ? "border-b bg-accent" : "border-b"
              }
            >
              <td className="p-2">
                <button
                  className="text-left underline underline-offset-4"
                  onClick={() => onSelect(edge.id)}
                >
                  {names.get(edge.source)} → {names.get(edge.target)}
                </button>
              </td>
              <td className="p-2 text-xs">{edge.label}</td>
              <td className="p-2 text-right whitespace-nowrap tabular-nums">
                {money(edge.totalChallenge)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function EvidenceTable({ rows }: { rows: GraphEvidence[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1080px] text-left text-sm">
        <thead className="border-b text-xs text-muted-foreground">
          <tr>
            {[
              "Invoice",
              "Repairer",
              "Repair item",
              "Billed price",
              "In-house P90",
              "Historical claims P90",
              "External reference",
              "Supported price",
              "Challenge amount",
              "Status",
            ].map((title) => (
              <th key={title} className="px-3 py-3">
                {title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={evidenceKey(row)} className="border-b last:border-0">
              <td className="px-3 py-3 font-medium">
                {row.invoiceNumber || row.invoiceId}
              </td>
              <td className="px-3 py-3">{row.repairer}</td>
              <td className="px-3 py-3">{row.description}</td>
              {[
                row.billedPrice,
                row.inHouseP90,
                row.historicalClaimsP90,
                row.externalReferencePrice,
                row.supportedPrice,
                row.challengeAmount,
              ].map((value, index) => (
                <td
                  key={index}
                  className="px-3 py-3 whitespace-nowrap tabular-nums"
                >
                  {money(value)}
                </td>
              ))}
              <td className="px-3 py-3">
                <Badge variant="outline">
                  {row.status.replaceAll("_", " ")}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
