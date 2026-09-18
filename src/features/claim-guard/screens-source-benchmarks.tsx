import { Fragment, useEffect, useState } from "react"
import { AlertCircleIcon, ChevronDownIcon, ChevronRightIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { isUnknownCategory, money, observationsLabel } from "./benchmark-analysis-rows"
import {
  BENCHMARK_SOURCES,
  fetchSourceBenchmarks,
  type BenchmarkRow,
  type BenchmarkSource,
  type SourceBenchmarksPayload,
  type VehicleCategorySource,
} from "./benchmark-api"
import { EvidenceTable, VehicleCategoryBadge } from "./benchmark-evidence"
import { documentApiErrorMessage } from "./document-api"
import { ScreenHeading } from "./shared"

function rowKey(row: BenchmarkRow) {
  return `${row.vehicle_category}::${row.repair_item_key}`
}

/** Grouped by vehicle category -- the benchmark dimension -- with Unknown
 * last, then by repair item. */
function orderedRows(rows: BenchmarkRow[]) {
  return [...rows].sort(
    (a, b) =>
      Number(isUnknownCategory(a.vehicle_category)) -
        Number(isUnknownCategory(b.vehicle_category)) ||
      a.vehicle_category.localeCompare(b.vehicle_category) ||
      a.repair_item.localeCompare(b.repair_item)
  )
}

/** The screen body, separate from the fetch so it renders from a payload in
 * tests. `evidenceOpen: "all"` opens every evidence row (a test has no
 * pointer to click the toggle). */
export function SourceBenchmarksView({
  payload,
  loading,
  error,
  onUpload,
  evidenceOpen,
}: {
  payload: SourceBenchmarksPayload | null
  loading: boolean
  error: string | null
  onUpload: () => void
  evidenceOpen?: "all"
}) {
  const [open, setOpen] = useState<Set<string>>(new Set())
  const isOpen = (key: string) => evidenceOpen === "all" || open.has(key)
  const toggle = (key: string) =>
    setOpen((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  if (error)
    return (
      <Alert variant="destructive">
        <AlertCircleIcon />
        <AlertTitle>Benchmarks could not be loaded</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    )
  if (loading || !payload)
    return (
      <p className="text-sm text-muted-foreground">Computing the benchmarks…</p>
    )

  if (payload.invoice_count === 0)
    return (
      <Card className="border-dashed">
        <CardHeader>
          <CardTitle>No {payload.label} uploaded yet</CardTitle>
          <CardDescription>
            This source's benchmark is computed only from the documents
            uploaded to it -- no seed data, nothing synthetic. Upload its
            repair invoices and engineer assessments and approve their mapping,
            and the P90s appear here.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={onUpload}>Upload documents</Button>
        </CardContent>
      </Card>
    )

  const categorySources = new Map<string, VehicleCategorySource>(
    payload.vehicle_categories.map((entry) => [entry.category, entry.source])
  )
  const rows = orderedRows(payload.rows)

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Vehicle categories</CardTitle>
          <CardDescription>
            The documents do not print a category, so each vehicle's comes
            from the category lookup, from AI when the lookup does not know the
            make and model, or -- when neither does -- it is Unknown. Unknown
            is benchmarked within itself and never mixed into a real class.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="flex flex-col gap-2">
            {payload.vehicle_categories.map((entry) => (
              <li
                key={entry.category}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2"
              >
                <VehicleCategoryBadge
                  category={entry.category}
                  source={entry.source}
                />
                <span className="text-sm text-muted-foreground tabular-nums">
                  {entry.invoice_count}{" "}
                  {entry.invoice_count === 1 ? "invoice" : "invoices"}
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>P90 per repair item, per vehicle category</CardTitle>
          <CardDescription>
            Only invoices in a category feed that category's P90, and only
            line items -- a rolled-up invoice total is never benchmarked; its
            line items come from the paired engineer assessment. A P90 from a
            single observation is that observation, which is why n is printed
            beside every P90.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {rows.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              {payload.invoice_count}{" "}
              {payload.invoice_count === 1 ? "invoice is" : "invoices are"} in
              this source, but no line item has been benchmarked yet. Approve
              the mapping on Document intelligence so the documents are read.
            </p>
          ) : (
            <div data-testid="benchmark-table" className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8">
                      <span className="sr-only">Evidence</span>
                    </TableHead>
                    <TableHead>Vehicle category</TableHead>
                    <TableHead>Repair item</TableHead>
                    <TableHead className="text-right">n</TableHead>
                    <TableHead className="text-right">P90</TableHead>
                    <TableHead className="text-right">Median</TableHead>
                    <TableHead className="text-right">Min</TableHead>
                    <TableHead className="text-right">Max</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => {
                    const key = rowKey(row)
                    const expanded = isOpen(key)
                    const detailId = `benchmark-evidence-${key}`
                    return (
                      <Fragment key={key}>
                        <TableRow>
                          <TableCell>
                            <button
                              type="button"
                              onClick={() => toggle(key)}
                              aria-expanded={expanded}
                              aria-controls={detailId}
                              aria-label={`${expanded ? "Hide" : "Show"} evidence for ${row.repair_item} (${row.vehicle_category})`}
                              className="text-muted-foreground transition-colors hover:text-foreground"
                            >
                              {expanded ? (
                                <ChevronDownIcon className="size-4" />
                              ) : (
                                <ChevronRightIcon className="size-4" />
                              )}
                            </button>
                          </TableCell>
                          <TableCell>
                            <VehicleCategoryBadge
                              category={row.vehicle_category}
                              source={categorySources.get(row.vehicle_category)}
                              showSource={false}
                            />
                          </TableCell>
                          <TableCell className="font-medium">
                            {row.repair_item}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {row.observations}
                          </TableCell>
                          <TableCell
                            data-testid="p90-cell"
                            className="text-right tabular-nums"
                          >
                            <span className="font-semibold">
                              {money(row.p90)}
                            </span>{" "}
                            <span className="text-xs text-muted-foreground">
                              {observationsLabel(row.observations)}
                              {row.observations === 1
                                ? " · single observation"
                                : ""}
                            </span>
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {money(row.median)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {money(row.min)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {money(row.max)}
                          </TableCell>
                        </TableRow>
                        {expanded ? (
                          <TableRow id={detailId}>
                            <TableCell colSpan={8} className="bg-muted/30 p-3">
                              <EvidenceTable rows={row.evidence} />
                            </TableCell>
                          </TableRow>
                        ) : null}
                      </Fragment>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </>
  )
}

/** Benchmark computation for one source: "vehicle category is this, repair
 * item is this … just the calculation on what you have extracted." */
export function SourceBenchmarksScreen({
  caseReference,
  source,
  onUpload,
}: {
  caseReference: string
  source: BenchmarkSource
  onUpload: () => void
}) {
  const [payload, setPayload] = useState<SourceBenchmarksPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    void fetchSourceBenchmarks(caseReference, source)
      .then((next) => {
        if (!active) return
        setPayload(next)
        setError(null)
      })
      .catch((e) => {
        if (!active) return
        setPayload(null)
        setError(documentApiErrorMessage(e))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [caseReference, source])

  return (
    <>
      <ScreenHeading
        title={`${BENCHMARK_SOURCES[source].label} · Benchmark computation`}
        description={`P90 per repair item per vehicle category, calculated only on what has been extracted from ${BENCHMARK_SOURCES[source].label.toLowerCase()}.${payload ? ` Threshold ${payload.threshold_pct}%.` : ""}`}
      />
      <SourceBenchmarksView
        payload={payload}
        loading={loading}
        error={error}
        onUpload={onUpload}
      />
    </>
  )
}
