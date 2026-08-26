import { useEffect, useMemo, useState } from "react"
import {
  ArrowLeftIcon,
  Building2Icon,
  CirclePoundSterlingIcon,
  EyeIcon,
  NetworkIcon,
  ReceiptTextIcon,
  WrenchIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type {
  BenchmarkDashboardPayload,
  BenchmarkExceptionPayload,
  ChallengeKnowledgeGraphPayload,
} from "@/lib/api"
import { fetchChallengeKnowledgeGraph } from "@/lib/api"

import { DataCard, ScreenHeading } from "./shared"

const GRAPH_WIDTH = 1080
const GRAPH_PADDING = 86
const demoRepairerTrends: BenchmarkDashboardPayload["repairerTrends"] = [
  {
    repairer: "Pilot Repair Network",
    challengeCount: 2,
    invoiceCount: 2,
    itemCount: 1,
    totalDifference: 490,
    maximumDifference: 260,
    items: [
      {
        ontologyItemId: "PART-BUMPER",
        item: "Front bumper repair",
        challengeCount: 2,
        invoiceCount: 2,
        totalDifference: 490,
        maximumDifference: 260,
        maximumPercentageAboveP90: 21.3,
        exceptions: [
          {
            observationId: "demo-graph-1",
            invoiceNumber: "INV-007",
            repairer: "Pilot Repair Network",
            description: "Front bumper repair",
            amount: 1480,
            p90: 1220,
            difference: 260,
            percentageAboveP90: 21.3,
            historicalCount: 6,
          },
          {
            observationId: "demo-graph-2",
            invoiceNumber: "INV-008",
            repairer: "Pilot Repair Network",
            description: "Repair front bumper",
            amount: 1445,
            p90: 1215,
            difference: 230,
            percentageAboveP90: 18.9,
            historicalCount: 7,
          },
        ],
      },
    ],
  },
]

function graphPayloadToRepairerTrends(
  payload: ChallengeKnowledgeGraphPayload
): BenchmarkDashboardPayload["repairerTrends"] {
  return payload.repairers.map((repairer) => ({
    repairer: repairer.name,
    challengeCount: repairer.challengeCount,
    invoiceCount: repairer.invoiceCount,
    itemCount: payload.edges.filter((edge) => edge.repairer === repairer.name)
      .length,
    totalDifference: repairer.totalChallenge,
    maximumDifference: Math.max(
      0,
      ...payload.edges
        .filter((edge) => edge.repairer === repairer.name)
        .map((edge) => edge.maximumChallenge)
    ),
    items: payload.edges
      .filter((edge) => edge.repairer === repairer.name)
      .map((edge) => ({
        ontologyItemId: edge.itemId,
        item: edge.item,
        challengeCount: edge.challengeCount,
        invoiceCount: edge.invoiceCount,
        totalDifference: edge.totalChallenge,
        maximumDifference: edge.maximumChallenge,
        maximumPercentageAboveP90: Math.max(
          0,
          ...edge.evidence.map((row) =>
            row.billedPrice > 0
              ? (row.challengeAmount / row.billedPrice) * 100
              : 0
          )
        ),
        exceptions: edge.evidence.map((row) => ({
          observationId: row.lineId,
          invoiceNumber: row.invoiceNumber,
          repairer: row.repairer,
          description: row.description,
          amount: row.billedPrice,
          p90: row.supportedPrice,
          difference: row.challengeAmount,
          percentageAboveP90:
            row.billedPrice > 0
              ? (row.challengeAmount / row.billedPrice) * 100
              : 0,
          historicalCount: row.historicalClaimsP90 == null ? 0 : 1,
        })),
      })),
  }))
}

type GraphSelection =
  | { kind: "repairer"; key: string }
  | { kind: "item"; key: string }
  | { kind: "edge"; key: string }

function preciseMoney(value: number) {
  return `£${value.toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function graphKey(kind: GraphSelection["kind"], key: string) {
  return `${kind}:${key}`
}

function graphLabelLines(value: string, maximumCharacters = 20) {
  const words = value.trim().split(/\s+/)
  const lines: string[] = []
  for (const word of words) {
    const current = lines.at(-1)
    if (!current || current.length + word.length + 1 > maximumCharacters) {
      lines.push(word)
    } else {
      lines[lines.length - 1] = `${current} ${word}`
    }
  }
  if (lines.length <= 2) return lines
  return [lines[0], `${lines.slice(1).join(" ").slice(0, maximumCharacters - 1)}…`]
}

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
  const [repairerTrends, setRepairerTrends] =
    useState<BenchmarkDashboardPayload["repairerTrends"]>(
      apiMode === "demo" ? demoRepairerTrends : []
    )
  const [selection, setSelection] = useState<GraphSelection | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const requestKey = `${caseReference}:${challengeThreshold}`
  const [loadedRequestKey, setLoadedRequestKey] = useState<string | null>(
    apiMode === "demo" ? requestKey : null
  )
  const loading = apiMode === "api" && loadedRequestKey !== requestKey

  useEffect(() => {
    if (apiMode === "demo") return
    void fetchChallengeKnowledgeGraph(caseReference, challengeThreshold)
      .then((result) => {
        setRepairerTrends(graphPayloadToRepairerTrends(result))
        setLoadError(null)
      })
      .catch(() => {
        setLoadError("The live challenge network could not be loaded.")
      })
      .finally(() => setLoadedRequestKey(requestKey))
  }, [apiMode, caseReference, challengeThreshold, requestKey])

  const graph = useMemo(() => {
    const repairers = repairerTrends.slice(0, 8)
    const itemMap = new Map<
      string,
      {
        id: string
        label: string
        invoiceNumbers: Set<string>
        challengeCount: number
        totalDifference: number
      }
    >()
    for (const repairer of repairers) {
      for (const item of repairer.items) {
        const current = itemMap.get(item.ontologyItemId) ?? {
          id: item.ontologyItemId,
          label: item.item,
          invoiceNumbers: new Set<string>(),
          challengeCount: 0,
          totalDifference: 0,
        }
        item.exceptions.forEach((row) => current.invoiceNumbers.add(row.invoiceNumber))
        current.challengeCount += item.challengeCount
        current.totalDifference += item.totalDifference
        itemMap.set(item.ontologyItemId, current)
      }
    }
    const items = Array.from(itemMap.values())
      .sort(
        (left, right) =>
          right.invoiceNumbers.size - left.invoiceNumbers.size ||
          right.challengeCount - left.challengeCount ||
          right.totalDifference - left.totalDifference ||
          left.label.localeCompare(right.label)
      )
      .slice(0, 10)
    const itemIds = new Set(items.map((item) => item.id))
    const edges = repairers.flatMap((repairer, repairerIndex) =>
      repairer.items
        .filter((item) => itemIds.has(item.ontologyItemId))
        .map((item) => ({
          key: `${repairer.repairer}:${item.ontologyItemId}`,
          repairer: repairer.repairer,
          repairerIndex,
          itemId: item.ontologyItemId,
          itemIndex: items.findIndex(
            (candidate) => candidate.id === item.ontologyItemId
          ),
          item: item.item,
          challengeCount: item.challengeCount,
          invoiceCount: item.invoiceCount,
          totalDifference: item.totalDifference,
          maximumDifference: item.maximumDifference,
          maximumPercentageAboveP90: item.maximumPercentageAboveP90,
          exceptions: item.exceptions,
        }))
    )
    return { repairers, items, edges }
  }, [repairerTrends])

  const effectiveSelection = useMemo(() => {
    if (!graph.repairers.length) return null
    const availableKeys = new Set([
      ...graph.repairers.map((row) => graphKey("repairer", row.repairer)),
      ...graph.items.map((row) => graphKey("item", row.id)),
      ...graph.edges.map((row) => graphKey("edge", row.key)),
    ])
    return selection && availableKeys.has(graphKey(selection.kind, selection.key))
      ? selection
      : ({ kind: "repairer", key: graph.repairers[0].repairer } satisfies GraphSelection)
  }, [graph, selection])

  const selectedEvidence = useMemo(() => {
    if (!effectiveSelection) return []
    const rows: BenchmarkExceptionPayload[] =
      effectiveSelection.kind === "repairer"
        ? graph.edges
            .filter((edge) => edge.repairer === effectiveSelection.key)
            .flatMap((edge) => edge.exceptions)
        : effectiveSelection.kind === "item"
          ? graph.edges
              .filter((edge) => edge.itemId === effectiveSelection.key)
              .flatMap((edge) => edge.exceptions)
          : graph.edges.find((edge) => edge.key === effectiveSelection.key)?.exceptions ?? []
    return rows.toSorted(
      (left, right) => right.difference - left.difference || left.invoiceNumber.localeCompare(right.invoiceNumber)
    )
  }, [effectiveSelection, graph.edges])

  const selectedTitle = useMemo(() => {
    if (!effectiveSelection) return "Select a node or connection"
    if (effectiveSelection.kind === "repairer") return effectiveSelection.key
    if (effectiveSelection.kind === "item") {
      return graph.items.find((item) => item.id === effectiveSelection.key)?.label ?? effectiveSelection.key
    }
    const edge = graph.edges.find((item) => item.key === effectiveSelection.key)
    return edge ? `${edge.repairer} → ${edge.item}` : effectiveSelection.key
  }, [effectiveSelection, graph.edges, graph.items])

  const allEvidence = graph.edges.flatMap((edge) => edge.exceptions)
  const challengedInvoiceCount = new Set(allEvidence.map((row) => row.invoiceNumber)).size
  const totalPotentialReduction = allEvidence.reduce(
    (total, row) => total + row.difference,
    0
  )
  const topRepairer = graph.repairers[0]
  const topItem = graph.items[0]
  const maxRepairerInvoices = Math.max(
    1,
    ...graph.repairers.map((repairer) => repairer.invoiceCount)
  )
  const maxRepairerDifference = Math.max(
    1,
    ...graph.repairers.map((repairer) => repairer.totalDifference)
  )
  const maxItemInvoices = Math.max(
    1,
    ...graph.items.map((item) => item.invoiceNumbers.size)
  )
  const rowGap = 94
  const graphHeight = Math.max(
    430,
    GRAPH_PADDING * 2 +
      Math.max(graph.repairers.length, graph.items.length, 1) * rowGap
  )
  const nodeY = (index: number, count: number) =>
    GRAPH_PADDING +
    (count <= 1
      ? (graphHeight - GRAPH_PADDING * 2) / 2
      : index * ((graphHeight - GRAPH_PADDING * 2) / (count - 1)))
  const repairerRadius = (invoiceCount: number) =>
    30 + 24 * Math.sqrt(invoiceCount / maxRepairerInvoices)
  const itemHeight = (invoiceCount: number) =>
    54 + 18 * Math.sqrt(invoiceCount / maxItemInvoices)
  const isSelected = (kind: GraphSelection["kind"], key: string) =>
    effectiveSelection?.kind === kind && effectiveSelection.key === key
  const selectFromKeyboard = (
    event: React.KeyboardEvent<SVGGElement | SVGPathElement>,
    value: GraphSelection
  ) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      setSelection(value)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <ScreenHeading
        title="Repairer knowledge graph"
        description="Explore the repairers, repair items and invoices connected by actual positive price-challenge outcomes."
        action={
          <Button type="button" variant="outline" onClick={onBack}>
            <ArrowLeftIcon aria-hidden />
            Back to benchmarks
          </Button>
        }
      />

      {loadError ? (
        <Alert variant="destructive">
          <NetworkIcon aria-hidden />
          <AlertTitle>Knowledge graph unavailable</AlertTitle>
          <AlertDescription>{loadError}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <DataCard title="Most challenged repairer" description="Ranked by distinct challenged invoices">
          <div className="flex items-start gap-3">
            <Building2Icon className="mt-1 size-5 text-primary" aria-hidden />
            <div>
              <p className="font-semibold">{topRepairer?.repairer ?? "—"}</p>
              <p className="text-sm text-muted-foreground">
                {topRepairer ? `${topRepairer.invoiceCount} invoices · ${topRepairer.challengeCount} lines` : "No qualifying challenges"}
              </p>
            </div>
          </div>
        </DataCard>
        <DataCard title="Most challenged item" description="Across all repairers">
          <div className="flex items-start gap-3">
            <WrenchIcon className="mt-1 size-5 text-destructive" aria-hidden />
            <div>
              <p className="font-semibold">{topItem?.label ?? "—"}</p>
              <p className="text-sm text-muted-foreground">
                {topItem ? `${topItem.invoiceNumbers.size} challenged invoices` : "No qualifying challenges"}
              </p>
            </div>
          </div>
        </DataCard>
        <DataCard title="Challenged invoices" description="Unique invoices with positive challenge outcomes">
          <div className="flex items-center gap-3">
            <ReceiptTextIcon className="size-5 text-primary" aria-hidden />
            <p className="text-2xl font-semibold tabular-nums">{challengedInvoiceCount}</p>
          </div>
        </DataCard>
        <DataCard title="Potential reduction" description="Sum of current positive challenge amounts">
          <div className="flex items-center gap-3">
            <CirclePoundSterlingIcon className="size-5 text-destructive" aria-hidden />
            <p className="text-2xl font-semibold tabular-nums">
              {preciseMoney(totalPotentialReduction)}
            </p>
          </div>
        </DataCard>
      </div>

      <DataCard
        title="Repairer → challenged repair item"
        description="Circle size shows challenged invoices, colour intensity shows total potential reduction, and connection thickness shows how many invoices contain that relationship. Select any element to inspect its evidence."
        action={<Badge variant="outline">Challenge outcomes</Badge>}
      >
        {loading && !graph.edges.length ? (
          <Alert>
            <NetworkIcon aria-hidden />
            <AlertTitle>Loading uploaded-invoice relationships</AlertTitle>
            <AlertDescription>
              Building the graph from the current challenged-invoice results.
            </AlertDescription>
          </Alert>
        ) : graph.edges.length ? (
          <div className="overflow-x-auto rounded-lg border bg-muted/20">
            <svg
              className="min-w-[860px]"
              viewBox={`0 0 ${GRAPH_WIDTH} ${graphHeight}`}
              role="img"
              aria-label="Interactive knowledge graph connecting repairers to repair items with benchmark challenges"
            >
              <defs>
                <filter id="graph-shadow" x="-20%" y="-20%" width="140%" height="140%">
                  <feDropShadow dx="0" dy="2" stdDeviation="3" floodOpacity="0.14" />
                </filter>
              </defs>

              {graph.edges.map((edge) => {
                const startY = nodeY(edge.repairerIndex, graph.repairers.length)
                const endY = nodeY(edge.itemIndex, graph.items.length)
                const startX = 250 + repairerRadius(graph.repairers[edge.repairerIndex].invoiceCount)
                const selected = isSelected("edge", edge.key)
                const path = `M ${startX} ${startY} C 485 ${startY}, 580 ${endY}, 730 ${endY}`
                return (
                  <g key={edge.key}>
                    <path
                      d={path}
                      fill="none"
                      stroke="transparent"
                      strokeWidth="18"
                      className="cursor-pointer"
                      role="button"
                      tabIndex={0}
                      aria-label={`Inspect ${edge.repairer} and ${edge.item}`}
                      onClick={() => setSelection({ kind: "edge", key: edge.key })}
                      onKeyDown={(event) => selectFromKeyboard(event, { kind: "edge", key: edge.key })}
                    />
                    <path
                      d={path}
                      fill="none"
                      stroke="var(--destructive)"
                      strokeOpacity={selected ? 0.9 : 0.38}
                      strokeWidth={Math.min(11, 2.5 + edge.invoiceCount * 1.7)}
                      pointerEvents="none"
                    />
                  </g>
                )
              })}

              {graph.repairers.map((repairer, index) => {
                const y = nodeY(index, graph.repairers.length)
                const radius = repairerRadius(repairer.invoiceCount)
                const labelLines = graphLabelLines(repairer.repairer)
                const intensity = 0.18 + 0.5 * (repairer.totalDifference / maxRepairerDifference)
                const selected = isSelected("repairer", repairer.repairer)
                return (
                  <g
                    key={repairer.repairer}
                    filter="url(#graph-shadow)"
                    className="cursor-pointer"
                    role="button"
                    tabIndex={0}
                    aria-label={`Inspect repairer ${repairer.repairer}`}
                    onClick={() => setSelection({ kind: "repairer", key: repairer.repairer })}
                    onKeyDown={(event) => selectFromKeyboard(event, { kind: "repairer", key: repairer.repairer })}
                  >
                    <text x="180" y={y - 15} textAnchor="end" fontSize="12" fontWeight="600" fill="currentColor">
                      {labelLines.map((line, lineIndex) => (
                        <tspan key={line} x="180" dy={lineIndex ? 15 : 0}>
                          {line}
                        </tspan>
                      ))}
                    </text>
                    <text x="180" y={y + 18} textAnchor="end" fontSize="11" fill="var(--muted-foreground)">
                      {repairer.invoiceCount} invoice{repairer.invoiceCount === 1 ? "" : "s"} · {preciseMoney(repairer.totalDifference)}
                    </text>
                    <circle
                      cx="250"
                      cy={y}
                      r={radius}
                      fill="var(--destructive)"
                      fillOpacity={intensity}
                      stroke={selected ? "var(--primary)" : "var(--destructive)"}
                      strokeWidth={selected ? 4 : 2}
                    />
                    <text x="250" y={y + 5} textAnchor="middle" fontSize="15" fontWeight="700" fill="currentColor">
                      {repairer.invoiceCount}
                    </text>
                  </g>
                )
              })}

              {graph.items.map((item, index) => {
                const y = nodeY(index, graph.items.length)
                const height = itemHeight(item.invoiceNumbers.size)
                const selected = isSelected("item", item.id)
                return (
                  <g
                    key={item.id}
                    filter="url(#graph-shadow)"
                    className="cursor-pointer"
                    role="button"
                    tabIndex={0}
                    aria-label={`Inspect repair item ${item.label}`}
                    onClick={() => setSelection({ kind: "item", key: item.id })}
                    onKeyDown={(event) => selectFromKeyboard(event, { kind: "item", key: item.id })}
                  >
                    <rect
                      x="730"
                      y={y - height / 2}
                      width="300"
                      height={height}
                      rx="16"
                      fill="var(--card)"
                      stroke={selected ? "var(--primary)" : "var(--destructive)"}
                      strokeWidth={selected ? 4 : 2}
                      strokeOpacity="0.8"
                    />
                    <circle cx="756" cy={y} r="9" fill="var(--destructive)" />
                    <text x="776" y={y - 5} fontSize="14" fontWeight="600" fill="currentColor">
                      {item.label.slice(0, 31)}
                    </text>
                    <text x="776" y={y + 17} fontSize="11" fill="var(--muted-foreground)">
                      {item.invoiceNumbers.size} invoice{item.invoiceNumbers.size === 1 ? "" : "s"} · {item.challengeCount} lines · {preciseMoney(item.totalDifference)}
                    </text>
                  </g>
                )
              })}
            </svg>
          </div>
        ) : (
          <Alert>
            <NetworkIcon aria-hidden />
            <AlertTitle>No challenge relationships at this setting</AlertTitle>
            <AlertDescription>
              The graph appears when the supported-price calculation produces a positive challenge that passes both review gates.
            </AlertDescription>
          </Alert>
        )}
      </DataCard>

      {graph.edges.length ? (
        <DataCard
          title="Relationship summary"
          description="The graph connections in an exact business table. Select a row to see the invoices behind it."
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] text-left text-sm">
              <thead className="border-b bg-muted/50 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-3 font-medium">Repairer</th>
                  <th className="px-3 py-3 font-medium">Canonical repair item</th>
                  <th className="px-3 py-3 text-right font-medium">Invoices</th>
                  <th className="px-3 py-3 text-right font-medium">Lines</th>
                  <th className="px-3 py-3 text-right font-medium">Total difference</th>
                  <th className="px-3 py-3 text-right font-medium">Largest difference</th>
                  <th className="px-3 py-3 text-right font-medium">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {graph.edges.map((edge) => (
                  <tr key={edge.key} className="border-b last:border-0">
                    <td className="px-3 py-3 font-medium">{edge.repairer}</td>
                    <td className="px-3 py-3 text-muted-foreground">{edge.item}</td>
                    <td className="px-3 py-3 text-right tabular-nums">{edge.invoiceCount}</td>
                    <td className="px-3 py-3 text-right tabular-nums">{edge.challengeCount}</td>
                    <td className="px-3 py-3 text-right font-medium text-destructive tabular-nums">
                      {preciseMoney(edge.totalDifference)}
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums">
                      {preciseMoney(edge.maximumDifference)} · +{edge.maximumPercentageAboveP90.toFixed(1)}%
                    </td>
                    <td className="px-3 py-3 text-right">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => setSelection({ kind: "edge", key: edge.key })}
                      >
                        <EyeIcon aria-hidden />
                        View {edge.invoiceCount}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DataCard>
      ) : null}

      {effectiveSelection ? (
        <DataCard
          title={`Evidence · ${selectedTitle}`}
          description="Every row is a stored invoice line with a positive challenge produced by the governed supported-price formula."
          action={<Badge variant="outline">{selectedEvidence.length} challenged lines</Badge>}
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-left text-sm">
              <thead className="border-b bg-muted/50 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-3 font-medium">Invoice</th>
                  <th className="px-3 py-3 font-medium">Repairer</th>
                  <th className="px-3 py-3 font-medium">Original description</th>
                  <th className="px-3 py-3 text-right font-medium">Charged</th>
                  <th className="px-3 py-3 text-right font-medium">Supported price</th>
                  <th className="px-3 py-3 text-right font-medium">Difference</th>
                  <th className="px-3 py-3 text-right font-medium">Reduction</th>
                  <th className="px-3 py-3 text-right font-medium">Historical source</th>
                </tr>
              </thead>
              <tbody>
                {selectedEvidence.map((row) => (
                  <tr key={row.observationId} className="border-b last:border-0">
                    <td className="px-3 py-3 font-medium">{row.invoiceNumber}</td>
                    <td className="px-3 py-3 text-muted-foreground">{row.repairer}</td>
                    <td className="px-3 py-3 text-muted-foreground">{row.description ?? "—"}</td>
                    <td className="px-3 py-3 text-right tabular-nums">{preciseMoney(row.amount)}</td>
                    <td className="px-3 py-3 text-right tabular-nums">{preciseMoney(row.p90)}</td>
                    <td className="px-3 py-3 text-right font-medium text-destructive tabular-nums">
                      +{preciseMoney(row.difference)}
                    </td>
                    <td className="px-3 py-3 text-right font-medium text-destructive tabular-nums">
                      {row.percentageAboveP90.toFixed(1)}%
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums">
                      {row.historicalCount ? "Available" : "Not available"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DataCard>
      ) : null}
    </div>
  )
}
