import { useEffect, useMemo, useRef, useState } from "react"
import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  DatabaseIcon,
  EyeIcon,
  Share2Icon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type {
  BenchmarkDashboardPayload,
  BenchmarkExceptionPayload,
  BenchmarkObservationPayload,
} from "@/lib/api"
import { fetchBenchmarkDashboard, fetchBenchmarkObservations } from "@/lib/api"

import { DataCard, MINIMUM_CHALLENGE_AMOUNT, ScreenHeading } from "./shared"
import type { ClaimWorkspace } from "./types"

const demoDashboard: BenchmarkDashboardPayload = {
  summary: {
    averageRepairCost: 432,
    averageLabourRate: 68,
    mostObservedItem: "Windscreen replacement",
    observationCount: 124,
    mostExpensiveRepairCategory: "Front bumper repair",
    mostExpensiveRepairAverage: 1250,
  },
  vehicleCategories: [
    { vehicleClass: "M1 / AB Hatchback", averageCost: 390, count: 28 },
    { vehicleClass: "M1 / AA Saloon", averageCost: 472, count: 24 },
    { vehicleClass: "M1 / AC Estate", averageCost: 498, count: 18 },
    { vehicleClass: "Segment: SUV", averageCost: 520, count: 31 },
    { vehicleClass: "N1 light goods", averageCost: 541, count: 23 },
  ],
  benchmarks: [
    {
      ontologyItemId: "PART-WINDSCREEN",
      item: "Windscreen replacement",
      vehicleClass: "M1 / AB Hatchback",
      statistics: {
        min: 380,
        max: 500,
        mean: 432,
        median: 420,
        mode: 410,
        p25: 410,
        p75: 450,
        p90: 480,
        outlierCount: 0,
        count: 5,
      },
      labourStatistics: {
        min: 62,
        max: 72,
        mean: 68,
        median: 68,
        mode: null,
        p25: 66,
        p75: 70,
        outlierCount: 0,
        count: 5,
      },
      sourceCount: 5,
      invoiceCount: 5,
      exceptionCount: 0,
      exceptionInvoiceCount: 0,
      exceptions: [],
      sampleStrength: "usable",
      latestObservedAt: "2026-06-18",
    },
    {
      ontologyItemId: "PART-BUMPER",
      item: "Front bumper repair",
      vehicleClass: "Segment: SUV",
      statistics: {
        min: 920,
        max: 1480,
        mean: 1250,
        median: 1220,
        mode: null,
        p25: 1100,
        p75: 1375,
        p90: 1445,
        outlierCount: 0,
        count: 8,
      },
      labourStatistics: {
        min: 64,
        max: 76,
        mean: 70,
        median: 69,
        mode: null,
        p25: 67,
        p75: 73,
        outlierCount: 0,
        count: 8,
      },
      sourceCount: 8,
      invoiceCount: 8,
      exceptionCount: 2,
      exceptionInvoiceCount: 2,
      exceptions: [
        {
          observationId: "demo-bumper-1",
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
          observationId: "demo-bumper-2",
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
      sampleStrength: "usable",
      latestObservedAt: "2026-07-02",
    },
  ],
  repairerTrends: [
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
          maximumPercentageAboveP90: 18.4,
          exceptions: [
            {
              observationId: "demo-bumper-1",
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
              observationId: "demo-bumper-2",
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
  ],
  filterOptions: {
    vehicleClasses: [
      "M1 / AB Hatchback",
      "M1 / AA Saloon",
      "M1 / AC Estate",
      "Segment: SUV",
      "N1 light goods",
    ],
    repairItems: [
      { id: "PART-WINDSCREEN", name: "Windscreen replacement" },
      { id: "PART-BUMPER", name: "Front bumper repair" },
    ],
  },
  appliedFilters: {
    vehicleClass: null,
    ontologyItemId: null,
    dateFrom: null,
    dateTo: null,
    minimumCount: 1,
    challengeThresholdPct: 10,
    minimumChallengeAmount: MINIMUM_CHALLENGE_AMOUNT,
  },
  dataQuality: {
    invoiceObservationCount: 126,
    validCostCount: 124,
    invalidOrMissingCostCount: 2,
    classifiedCount: 109,
    unclassifiedCount: 15,
    classifiedCoveragePct: 87.9,
    latestObservationDate: "2026-07-02",
  },
  definitions: {
    cost: "Invoice net line total, excluding estimates and credit notes.",
    labour: "Explicit labour rate, or an hourly labour line where available.",
    challengeGate:
      "A P90 exception must exceed the selected percentage threshold and the existing £5.00 minimum positive variance.",
    coverageNote:
      "Unclassified rows remain visible and are never guessed into a vehicle class.",
    officialClasses: {},
  },
}

function money(value: number | null, suffix = "") {
  return value === null
    ? "—"
    : `£${value.toLocaleString("en-GB", { maximumFractionDigits: 0 })}${suffix}`
}

function preciseMoney(value: number) {
  return `£${value.toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function signedMoney(value: number) {
  if (value === 0) return preciseMoney(0)
  return `${value > 0 ? "+" : "−"}${preciseMoney(Math.abs(value))}`
}

type BenchmarkSortKey =
  | "item"
  | "vehicleClass"
  | "invoiceCount"
  | "min"
  | "max"
  | "median"
  | "p90"
  | "exceptionInvoiceCount"
  | "totalChallenge"

type BenchmarkRow = BenchmarkDashboardPayload["benchmarks"][number]

function totalChallengeAmount(item: BenchmarkRow) {
  const total = item.exceptions.reduce((sum, row) => sum + row.difference, 0)
  return Math.round(total * 100) / 100
}

function benchmarkSortValue(item: BenchmarkRow, key: BenchmarkSortKey) {
  switch (key) {
    case "item":
      return item.item
    case "vehicleClass":
      return item.vehicleClass
    case "invoiceCount":
      return item.invoiceCount
    case "min":
      return item.statistics.min ?? Number.NEGATIVE_INFINITY
    case "max":
      return item.statistics.max ?? Number.NEGATIVE_INFINITY
    case "median":
      return item.statistics.median ?? Number.NEGATIVE_INFINITY
    case "p90":
      return item.statistics.p90 ?? Number.NEGATIVE_INFINITY
    case "exceptionInvoiceCount":
      return item.exceptionInvoiceCount
    case "totalChallenge":
      return totalChallengeAmount(item)
  }
}

export function BenchmarkDashboardScreen({
  apiMode,
  workspace,
  challengeThreshold,
  onChallengeThresholdChange,
  onOpenKnowledgeGraph,
}: {
  apiMode: "api" | "demo"
  workspace: ClaimWorkspace
  challengeThreshold: number
  onChallengeThresholdChange: (value: number) => void
  onOpenKnowledgeGraph: () => void
}) {
  const [dashboard, setDashboard] =
    useState<BenchmarkDashboardPayload>(demoDashboard)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [vehicleClass, setVehicleClass] = useState("all")
  const [repairItem, setRepairItem] = useState("all")
  const [minimumCount, setMinimumCount] = useState("1")
  const [sortKey, setSortKey] = useState<BenchmarkSortKey>("item")
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc")
  const [sourceRows, setSourceRows] = useState<BenchmarkObservationPayload[]>(
    []
  )
  const [exceptionRows, setExceptionRows] = useState<
    BenchmarkExceptionPayload[]
  >([])
  const [evidenceMode, setEvidenceMode] = useState<"sources" | "exceptions">(
    "sources"
  )
  const [sourceTitle, setSourceTitle] = useState<string | null>(null)
  const [sourceLoading, setSourceLoading] = useState(false)
  const sourcePanelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (apiMode === "demo") return
    void fetchBenchmarkDashboard({
      caseReference: workspace.claim.id,
      vehicleClass: vehicleClass === "all" ? undefined : vehicleClass,
      ontologyItemId: repairItem === "all" ? undefined : repairItem,
      minimumCount: Number(minimumCount),
      challengeThresholdPct: challengeThreshold,
    })
      .then((result) => {
        setDashboard(result)
        setLoadError(null)
      })
      .catch(() =>
        setLoadError(
          "Live benchmark data could not be loaded. Showing the pilot example."
        )
      )
  }, [
    apiMode,
    challengeThreshold,
    minimumCount,
    repairItem,
    vehicleClass,
    workspace.claim.id,
  ])

  const selectedInvoiceBenchmarks = workspace.lines.filter(
    (line) => line.p90Benchmark
  )
  const sortedBenchmarks = useMemo(
    () =>
      [...dashboard.benchmarks].sort((left, right) => {
        const leftValue = benchmarkSortValue(left, sortKey)
        const rightValue = benchmarkSortValue(right, sortKey)
        const comparison =
          typeof leftValue === "string" && typeof rightValue === "string"
            ? leftValue.localeCompare(rightValue, "en-GB", {
                sensitivity: "base",
              })
            : Number(leftValue) - Number(rightValue)
        if (comparison !== 0)
          return sortDirection === "asc" ? comparison : -comparison
        return left.item.localeCompare(right.item, "en-GB", {
          sensitivity: "base",
        })
      }),
    [dashboard.benchmarks, sortDirection, sortKey]
  )

  function changeSort(key: BenchmarkSortKey) {
    if (sortKey === key) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"))
      return
    }
    setSortKey(key)
    setSortDirection(key === "item" || key === "vehicleClass" ? "asc" : "desc")
  }

  function sortHeader(
    label: string,
    key: BenchmarkSortKey,
    alignment: "left" | "right" = "right"
  ) {
    const active = sortKey === key
    const SortIcon = active
      ? sortDirection === "asc"
        ? ArrowUpIcon
        : ArrowDownIcon
      : ArrowUpDownIcon
    return (
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={`h-auto w-full gap-1 px-0 py-0 text-xs font-medium hover:bg-transparent ${
          alignment === "right" ? "justify-end" : "justify-start"
        } ${active ? "text-foreground" : "text-muted-foreground"}`}
        onClick={() => changeSort(key)}
        aria-label={`Sort by ${label}, ${
          active
            ? sortDirection === "asc"
              ? "ascending"
              : "descending"
            : "not selected"
        }`}
      >
        {label}
        <SortIcon className="size-3.5" aria-hidden />
      </Button>
    )
  }

  function revealEvidencePanel() {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        sourcePanelRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        })
      })
    })
  }

  function showSources(item: BenchmarkDashboardPayload["benchmarks"][number]) {
    setSourceTitle(`${item.item} · ${item.vehicleClass}`)
    setEvidenceMode("sources")
    setSourceRows([])
    setExceptionRows([])
    setSourceLoading(true)
    revealEvidencePanel()
    if (item.sourceObservations) {
      setSourceRows(item.sourceObservations)
      setSourceLoading(false)
      return
    }
    if (apiMode === "demo") {
      setSourceRows([
        {
          id: "demo-source",
          invoiceDate: item.latestObservedAt,
          amount: item.statistics.median,
          vehicleClass: item.vehicleClass,
          vehicleMake: "Example",
          vehicleModel: "Vehicle",
          rawDescription: item.item,
          sourceRecordId: "PILOT-EXAMPLE",
          repairer: "Pilot Repair Network",
          source: { evidence_label: "Previous repair invoice" },
        },
      ])
      setSourceLoading(false)
      return
    }
    void fetchBenchmarkObservations(item.ontologyItemId, item.vehicleClass)
      .then((result) => {
        setSourceRows(result.observations)
        setLoadError(null)
      })
      .catch(() => setLoadError("The source observations could not be loaded."))
      .finally(() => setSourceLoading(false))
  }

  function showExceptions(
    item: BenchmarkDashboardPayload["benchmarks"][number]
  ) {
    setSourceTitle(`${item.item} · ${item.vehicleClass}`)
    setEvidenceMode("exceptions")
    setSourceRows([])
    setExceptionRows(item.exceptions)
    setSourceLoading(false)
    revealEvidencePanel()
  }

  return (
    <div className="flex flex-col gap-6">
      <ScreenHeading
        title="Repair benchmarks"
        description="Compare every uploaded invoice line with earlier mapped lines from the same batch."
        action={
          <Button
            type="button"
            variant="outline"
            onClick={onOpenKnowledgeGraph}
          >
            <Share2Icon aria-hidden />
            Open knowledge graph
          </Button>
        }
      />

      <Card>
        <CardContent className="grid gap-4 p-5 md:grid-cols-2 xl:grid-cols-4">
          <label className="grid gap-2 text-sm font-medium">
            Vehicle category
            <Select value={vehicleClass} onValueChange={setVehicleClass}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="all">All vehicle categories</SelectItem>
                  {dashboard.filterOptions.vehicleClasses.map((item) => (
                    <SelectItem key={item} value={item}>
                      {item}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </label>
          <label className="grid gap-2 text-sm font-medium">
            Repair item
            <Select value={repairItem} onValueChange={setRepairItem}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="all">All repair items</SelectItem>
                  {dashboard.filterOptions.repairItems.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </label>
          <label className="grid gap-2 text-sm font-medium">
            Minimum sample
            <Select value={minimumCount} onValueChange={setMinimumCount}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="1">1+ observations</SelectItem>
                  <SelectItem value="3">3+ observations</SelectItem>
                  <SelectItem value="10">10+ observations</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </label>
          <label className="grid gap-2 text-sm font-medium">
            P90 alert threshold
            <Select
              value={String(challengeThreshold)}
              onValueChange={(value) =>
                onChallengeThresholdChange(Number(value))
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="5">More than 5% above P90</SelectItem>
                  <SelectItem value="10">More than 10% above P90</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </label>
        </CardContent>
      </Card>

      <DataCard
        title="Aggregate repair benchmark summary"
        description={`All uploaded invoices in this claim batch. Red counts require both more than ${challengeThreshold}% above the earlier-invoice P90 and at least ${preciseMoney(MINIMUM_CHALLENGE_AMOUNT)} difference.`}
        action={<Badge variant="outline">P90 · interpolated</Badge>}
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1120px] text-left text-sm">
            <thead className="border-b bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-3">
                  {sortHeader("Repair item", "item", "left")}
                </th>
                <th className="px-3 py-3">
                  {sortHeader("Vehicle category", "vehicleClass", "left")}
                </th>
                <th className="px-3 py-3 text-right">
                  {sortHeader("Invoices", "invoiceCount")}
                </th>
                <th className="px-3 py-3 text-right">
                  {sortHeader("Min", "min")}
                </th>
                <th className="px-3 py-3 text-right">
                  {sortHeader("Max", "max")}
                </th>
                <th className="px-3 py-3 text-right">
                  {sortHeader("Median", "median")}
                </th>
                <th className="bg-primary/5 px-3 py-3 text-right font-semibold text-foreground">
                  {sortHeader("P90", "p90")}
                </th>
                <th className="bg-primary/5 px-3 py-3 text-right font-semibold text-foreground">
                  {sortHeader("Challenged invoices", "exceptionInvoiceCount")}
                </th>
                <th className="bg-destructive/5 px-3 py-3 text-right font-semibold text-foreground">
                  {sortHeader("Total challenge", "totalChallenge")}
                </th>
                <th className="px-3 py-3 text-right font-medium">
                  Invoices used
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedBenchmarks.map((item) => (
                <tr
                  key={`${item.ontologyItemId}-${item.vehicleClass}`}
                  className="border-b last:border-0"
                >
                  <td className="px-3 py-3 font-medium">
                    <div>{item.item}</div>
                    <details className="mt-1 text-xs font-normal text-muted-foreground">
                      <summary className="cursor-pointer select-none hover:text-foreground">
                        More statistics
                      </summary>
                      <div className="mt-2 grid min-w-[250px] grid-cols-2 gap-x-4 gap-y-1 rounded-md border bg-muted/30 p-2">
                        <span>Mean</span>
                        <span className="text-right tabular-nums">
                          {money(item.statistics.mean)}
                        </span>
                        <span>Mode</span>
                        <span className="text-right tabular-nums">
                          {money(item.statistics.mode)}
                        </span>
                        <span>Observations</span>
                        <span className="text-right tabular-nums">
                          {item.statistics.count}
                        </span>
                        <span>Labour mean</span>
                        <span className="text-right tabular-nums">
                          {money(item.labourStatistics.mean)}
                        </span>
                        <span>Labour median</span>
                        <span className="text-right tabular-nums">
                          {money(item.labourStatistics.median)}
                        </span>
                        <span>Labour observations</span>
                        <span className="text-right tabular-nums">
                          {item.labourStatistics.count}
                        </span>
                      </div>
                    </details>
                  </td>
                  <td className="px-3 py-3 text-muted-foreground">
                    {item.vehicleClass}
                  </td>
                  <td className="px-3 py-3 text-right tabular-nums">
                    {item.invoiceCount}
                  </td>
                  <td className="px-3 py-3 text-right tabular-nums">
                    {money(item.statistics.min)}
                  </td>
                  <td className="px-3 py-3 text-right tabular-nums">
                    {money(item.statistics.max)}
                  </td>
                  <td className="px-3 py-3 text-right tabular-nums">
                    {money(item.statistics.median)}
                  </td>
                  <td className="bg-primary/5 px-3 py-3 text-right font-semibold tabular-nums">
                    {money(item.statistics.p90 ?? null)}
                  </td>
                  <td className="bg-primary/5 px-3 py-3 text-right">
                    {item.exceptionInvoiceCount > 0 ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-auto border-destructive/40 py-1 text-destructive hover:text-destructive"
                        onClick={() => showExceptions(item)}
                      >
                        <EyeIcon aria-hidden />
                        {item.exceptionInvoiceCount} invoice
                        {item.exceptionInvoiceCount === 1 ? "" : "s"} ·{" "}
                        {item.exceptionCount} line
                        {item.exceptionCount === 1 ? "" : "s"}
                      </Button>
                    ) : (
                      <Badge variant="outline">0</Badge>
                    )}
                  </td>
                  <td
                    className={`bg-destructive/5 px-3 py-3 text-right font-semibold tabular-nums ${
                      item.exceptionCount > 0
                        ? "text-destructive"
                        : "text-muted-foreground"
                    }`}
                  >
                    {preciseMoney(totalChallengeAmount(item))}
                  </td>
                  <td className="px-3 py-3 text-right">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => showSources(item)}
                    >
                      <EyeIcon aria-hidden />
                      View {item.invoiceCount}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DataCard>

      {sourceTitle ? (
        <div ref={sourcePanelRef} aria-live="polite">
          <DataCard
            title={
              evidenceMode === "exceptions"
                ? "Above-threshold invoices"
                : "Source observations"
            }
            description={
              evidenceMode === "exceptions"
                ? `${sourceTitle}. Each row was compared only with earlier invoices and exceeded both challenge gates.`
                : `${sourceTitle}. These invoice rows are the evidence behind the selected benchmark.`
            }
          >
            {evidenceMode === "exceptions" ? (
              exceptionRows.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[760px] text-left text-sm">
                    <thead className="border-b bg-muted/50 text-xs text-muted-foreground">
                      <tr>
                        <th className="px-3 py-3 font-medium">Invoice</th>
                        <th className="px-3 py-3 font-medium">Repairer</th>
                        <th className="px-3 py-3 font-medium">
                          Original description
                        </th>
                        <th className="px-3 py-3 text-right font-medium">
                          Charged
                        </th>
                        <th className="px-3 py-3 text-right font-medium">
                          Earlier P90
                        </th>
                        <th className="px-3 py-3 text-right font-medium">
                          Difference
                        </th>
                        <th className="px-3 py-3 text-right font-medium">
                          Above P90
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {exceptionRows.map((row) => (
                        <tr
                          key={row.observationId}
                          className="border-b last:border-0"
                        >
                          <td className="px-3 py-3 font-medium">
                            {row.invoiceNumber}
                          </td>
                          <td className="px-3 py-3 text-muted-foreground">
                            {row.repairer}
                          </td>
                          <td className="px-3 py-3 text-muted-foreground">
                            {row.description ?? "—"}
                          </td>
                          <td className="px-3 py-3 text-right tabular-nums">
                            {preciseMoney(row.amount)}
                          </td>
                          <td className="px-3 py-3 text-right tabular-nums">
                            {preciseMoney(row.p90)}
                          </td>
                          <td className="px-3 py-3 text-right font-medium text-destructive tabular-nums">
                            +{preciseMoney(row.difference)}
                          </td>
                          <td className="px-3 py-3 text-right font-medium text-destructive tabular-nums">
                            +{row.percentageAboveP90.toFixed(1)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No invoices exceed the selected threshold for this benchmark.
                </p>
              )
            ) : sourceLoading ? (
              <p className="text-sm text-muted-foreground">
                Loading source observations…
              </p>
            ) : sourceRows.length ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <thead className="border-b bg-muted/50 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-3 font-medium">Invoice date</th>
                      <th className="px-3 py-3 font-medium">
                        Source reference
                      </th>
                      <th className="px-3 py-3 font-medium">
                        Original description
                      </th>
                      <th className="px-3 py-3 font-medium">Repairer</th>
                      <th className="px-3 py-3 font-medium">Vehicle</th>
                      <th className="px-3 py-3 text-right font-medium">
                        Net amount
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {sourceRows.map((row) => (
                      <tr key={row.id} className="border-b last:border-0">
                        <td className="px-3 py-3">{row.invoiceDate ?? "—"}</td>
                        <td className="px-3 py-3 font-medium">
                          {row.sourceRecordId ?? "—"}
                        </td>
                        <td className="px-3 py-3 text-muted-foreground">
                          {row.rawDescription ?? "—"}
                        </td>
                        <td className="px-3 py-3 text-muted-foreground">
                          {row.repairer}
                        </td>
                        <td className="px-3 py-3 text-muted-foreground">
                          {[row.vehicleMake, row.vehicleModel]
                            .filter(Boolean)
                            .join(" ") || row.vehicleClass}
                        </td>
                        <td className="px-3 py-3 text-right tabular-nums">
                          {money(row.amount)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No valid source observations match this benchmark.
              </p>
            )}
          </DataCard>
        </div>
      ) : null}

      <DataCard
        title={`Selected invoice · ${workspace.invoice.number}`}
        description={`Operational comparison: the selected invoice is excluded from its own P90. A challenge requires both more than ${challengeThreshold}% above P90 and at least ${preciseMoney(MINIMUM_CHALLENGE_AMOUNT)} difference.`}
        action={<Badge variant="outline">Current invoice excluded</Badge>}
      >
        {selectedInvoiceBenchmarks.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[780px] text-left text-sm">
              <thead className="border-b bg-muted/50 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-3 font-medium">Line item</th>
                  <th className="px-3 py-3 font-medium">Standard category</th>
                  <th className="px-3 py-3 text-right font-medium">Current</th>
                  <th className="px-3 py-3 text-right font-medium">P90</th>
                  <th className="px-3 py-3 text-right font-medium">
                    Difference
                  </th>
                  <th className="px-3 py-3 font-medium">Decision</th>
                  <th className="px-3 py-3 text-right font-medium">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {selectedInvoiceBenchmarks.map((line) => {
                  const benchmark = line.p90Benchmark!
                  const exceedsThreshold =
                    benchmark.percentageDifference > challengeThreshold &&
                    benchmark.difference >= MINIMUM_CHALLENGE_AMOUNT
                  return (
                    <tr
                      key={line.id}
                      className="border-b align-top last:border-0"
                    >
                      <td className="px-3 py-3 font-medium">
                        {line.description}
                      </td>
                      <td className="px-3 py-3 text-muted-foreground">
                        {benchmark.category}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">
                        {preciseMoney(benchmark.currentPrice)}
                      </td>
                      <td className="px-3 py-3 text-right font-semibold tabular-nums">
                        {preciseMoney(benchmark.p90)}
                      </td>
                      <td
                        className={`px-3 py-3 text-right tabular-nums ${
                          exceedsThreshold ? "text-destructive" : "text-success"
                        }`}
                      >
                        {signedMoney(benchmark.difference)}
                      </td>
                      <td className="px-3 py-3">
                        <Badge
                          variant={
                            exceedsThreshold ? "destructive" : "secondary"
                          }
                        >
                          {exceedsThreshold ? "Challenge" : "Within threshold"}
                        </Badge>
                      </td>
                      <td className="px-3 py-3 text-right">
                        <details className="group inline-block text-left">
                          <summary className="cursor-pointer list-none rounded-md border px-3 py-1.5 text-xs font-medium">
                            View {benchmark.historicalCount} prices
                          </summary>
                          <div className="mt-2 min-w-[340px] rounded-lg border bg-card p-3 shadow-sm">
                            <p className="mb-2 text-xs text-muted-foreground">
                              {benchmark.method}. Current invoice excluded.
                            </p>
                            <table className="w-full text-xs">
                              <thead className="text-muted-foreground">
                                <tr>
                                  <th className="py-1 text-left font-medium">
                                    Invoice
                                  </th>
                                  <th className="py-1 text-left font-medium">
                                    Description
                                  </th>
                                  <th className="py-1 text-right font-medium">
                                    Price
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {benchmark.observations.map((observation) => (
                                  <tr
                                    key={observation.lineId}
                                    className="border-t"
                                  >
                                    <td className="py-1.5 pr-2 font-medium">
                                      {observation.invoiceNumber}
                                    </td>
                                    <td className="py-1.5 pr-2 text-muted-foreground">
                                      {observation.description}
                                    </td>
                                    <td className="py-1.5 text-right tabular-nums">
                                      {preciseMoney(observation.price)}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </details>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <Alert>
            <DatabaseIcon />
            <AlertTitle>Not enough earlier matching prices yet</AlertTitle>
            <AlertDescription>
              P90 appears from the fourth relevant invoice because three earlier
              matching prices are required. Uploading or selecting later
              invoices does not change earlier decisions, and an invoice never
              benchmarks itself.
            </AlertDescription>
          </Alert>
        )}
      </DataCard>

      <p className="border-t pt-4 text-xs text-muted-foreground">
        Aggregate statistics use all valid stored invoice lines. Challenge
        counts use only earlier invoices, so the invoice being evaluated never
        contributes to its own P90.
        {loadError ? ` ${loadError}` : ""}
      </p>
    </div>
  )
}
