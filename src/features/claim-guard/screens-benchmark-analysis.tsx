import { Fragment, useEffect, useState } from "react"
import {
  AlertCircleIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  MailIcon,
} from "lucide-react"
import { toast } from "sonner"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

import {
  benchmarkCellState,
  challengeSummary,
  documentOrder,
  generatedByLabel,
  isChallenge,
  lowLineDistance,
  mailtoHref,
  money,
  observationsLabel,
  sortByChallengeLevel,
  toNumber,
} from "./benchmark-analysis-rows"
import {
  BENCHMARK_SOURCES,
  draftChallengeEmail,
  fetchBenchmarkAnalysis,
  type AnalysisBenchmark,
  type AnalysisLine,
  type BenchmarkAnalysisPayload,
  type BenchmarkSource,
  type ChallengeEmailDraft,
  type ChallengeLevel,
} from "./benchmark-api"
import {
  EvidenceTable,
  OriginBadge,
  VehicleCategoryBadge,
} from "./benchmark-evidence"
import { documentApiErrorMessage } from "./document-api"
import { SectionBreakdownDetail } from "./extracts-section"
import { Metric, ScreenHeading } from "./shared"

const SOURCES: BenchmarkSource[] = ["third_party", "aviva_dlg"]

export type AnalysisSort = "document" | "level"

const LEVEL_LABELS: Record<ChallengeLevel, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
}

function LevelBadge({ level }: { level: ChallengeLevel | null }) {
  if (!level) return <span className="text-muted-foreground">—</span>
  if (level === "low")
    return (
      <Badge
        variant="outline"
        className="border-amber-400 text-amber-800 dark:text-amber-300"
      >
        Low
      </Badge>
    )
  return <Badge variant="destructive">{LEVEL_LABELS[level]}</Badge>
}

/** One benchmark's cell. Red when the line violates it, amber when the line
 * is above it but inside the rule, and "No data" -- never £0.00 -- when the
 * source holds nothing for this repair item in this category. `n` sits
 * beside every P90. */
function BenchmarkCell({ benchmark }: { benchmark: AnalysisBenchmark }) {
  const state = benchmarkCellState(benchmark)
  return (
    <TableCell
      data-benchmark-state={state}
      className={cn(
        "text-right tabular-nums",
        state === "violated" && "bg-destructive/10 font-medium text-destructive",
        state === "above" &&
          "bg-amber-50 text-amber-800 dark:bg-amber-950/30 dark:text-amber-300"
      )}
    >
      {state === "no-data" ? (
        <span className="text-muted-foreground">No data</span>
      ) : (
        <>
          <span>{money(benchmark.p90)}</span>{" "}
          <span className="text-xs opacity-80">
            {observationsLabel(benchmark.observations)}
          </span>
          {toNumber(benchmark.difference_pct) != null &&
          (state === "violated" || state === "above") ? (
            <span className="block text-xs">
              +{benchmark.difference_pct}% over
            </span>
          ) : null}
        </>
      )}
    </TableCell>
  )
}

function ChallengeAmountCell({ line }: { line: AnalysisLine }) {
  if (isChallenge(line))
    return (
      <TableCell className="text-right tabular-nums">
        <span className="font-semibold text-destructive">
          {money(line.challenge.challenge_amount)}
        </span>
        {line.challenge.justified_amount ? (
          <span className="block text-xs text-muted-foreground">
            justified {money(line.challenge.justified_amount)}
          </span>
        ) : null}
      </TableCell>
    )
  if (line.challenge.level === "low") {
    const distance = lowLineDistance(line)
    return (
      <TableCell className="text-right text-xs text-amber-800 tabular-nums dark:text-amber-300">
        {distance != null ? `${money(distance)} above P90` : "Above P90"} · not
        counted
      </TableCell>
    )
  }
  return (
    <TableCell className="text-right text-muted-foreground">—</TableCell>
  )
}

/** The analysis itself, rendered from a payload so it can be tested without
 * a network. The `initial*` props seed the local state for the same reason:
 * a server render has no pointer to click the sort, a checkbox or a toggle. */
export function BenchmarkAnalysisView({
  analysis,
  onSelectInvoice,
  onDraftEmail,
  drafting,
  initialSort = "document",
  initialSelected = [],
  initialEvidenceOpen = [],
}: {
  analysis: BenchmarkAnalysisPayload
  onSelectInvoice: (invoiceId: string) => void
  onDraftEmail: (lineIds: string[]) => void
  drafting: boolean
  initialSort?: AnalysisSort
  initialSelected?: string[]
  initialEvidenceOpen?: string[]
}) {
  const [sort, setSort] = useState<AnalysisSort>(initialSort)
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(initialSelected)
  )
  const [evidenceOpen, setEvidenceOpen] = useState<Set<string>>(
    () => new Set(initialEvidenceOpen)
  )
  const { invoice } = analysis
  const lines =
    sort === "level"
      ? sortByChallengeLevel(analysis.lines)
      : documentOrder(analysis.lines)
  const summary = challengeSummary(analysis.lines)
  const challengeLines = lines.filter(isChallenge)
  const selectedIds = lines
    .filter((line) => selected.has(line.line_id) && isChallenge(line))
    .map((line) => line.line_id)
  const selectedTotal = challengeLines
    .filter((line) => selected.has(line.line_id))
    .reduce(
      (total, line) => total + (toNumber(line.challenge.challenge_amount) ?? 0),
      0
    )

  function toggleIn(
    setter: typeof setSelected,
    id: string,
    on?: boolean
  ) {
    setter((current) => {
      const next = new Set(current)
      if (on ?? !next.has(id)) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const vehicle =
    [invoice.vehicle_make, invoice.vehicle_model].filter(Boolean).join(" ") ||
    "Not printed"

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>
                Invoice {invoice.invoice_number ?? "number not printed"}
              </CardTitle>
              <CardDescription>
                Every line of this invoice, then every line of its engineer
                assessment, against the third-party P90 and the Aviva DLG P90
                for its vehicle category -- side by side, never blended.
              </CardDescription>
            </div>
            {analysis.live_invoices.length > 1 ? (
              <select
                className="h-9 min-w-56 rounded-md border bg-background px-3 text-sm"
                aria-label="New invoice to analyse"
                value={invoice.id}
                onChange={(event) => onSelectInvoice(event.target.value)}
              >
                {analysis.live_invoices.map((option) => (
                  <option key={option.id} value={option.id}>
                    {[option.invoice_number ?? "Number not printed", option.registration]
                      .filter(Boolean)
                      .join(" · ")}
                  </option>
                ))}
              </select>
            ) : null}
          </div>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">Vehicle</dt>
              <dd className="font-medium">{vehicle}</dd>
              <dd className="text-muted-foreground">
                {invoice.registration ?? "Registration not printed"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Vehicle category</dt>
              <dd className="mt-1">
                <VehicleCategoryBadge
                  category={invoice.vehicle_category}
                  source={invoice.vehicle_category_source}
                />
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">
                Paired engineer assessment
              </dt>
              <dd className="font-medium">
                {invoice.paired_assessment_number ?? (
                  <span className="font-normal text-muted-foreground">
                    No engineer assessment paired
                  </span>
                )}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Valuation rule</dt>
              <dd className="text-muted-foreground">
                Violated when over a P90 by more than {analysis.threshold_pct}%
                and by at least {money(analysis.minimum_challenge_amount)}.
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="grid gap-4 sm:grid-cols-3">
          <Metric
            label="Total challenge amount"
            value={money(summary.total)}
            hint="High and Medium lines only. Low lines are shown, never counted."
            emphasis={summary.total > 0}
          />
          <div className="min-w-0 px-1 py-1">
            <p className="text-xs font-medium text-muted-foreground">
              Challenges by level
            </p>
            <p className="mt-2 flex flex-wrap items-center gap-2 text-sm">
              <Badge variant="destructive">{summary.counts.high} high</Badge>
              <Badge variant="destructive">{summary.counts.medium} medium</Badge>
              <Badge
                variant="outline"
                className="border-amber-400 text-amber-800 dark:text-amber-300"
              >
                {summary.counts.low} low
              </Badge>
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              High: both benchmarks violated. Medium: one. Low: above a P90 but
              inside the rule.
            </p>
          </div>
          <Metric
            label="Selected for the email"
            value={money(selectedTotal)}
            hint={`${selectedIds.length} of ${challengeLines.length} challenges selected`}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>Line items against both benchmarks</CardTitle>
              <CardDescription>
                Red where a benchmark is violated, amber for a Low line. Select
                the challenges to pursue, then draft the email.
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="inline-flex rounded-md border p-0.5" role="group" aria-label="Order">
                <Button
                  size="sm"
                  variant={sort === "document" ? "secondary" : "ghost"}
                  aria-pressed={sort === "document"}
                  onClick={() => setSort("document")}
                >
                  As on the documents
                </Button>
                <Button
                  size="sm"
                  variant={sort === "level" ? "secondary" : "ghost"}
                  aria-pressed={sort === "level"}
                  onClick={() => setSort("level")}
                >
                  By challenge level
                </Button>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={!challengeLines.length}
                onClick={() =>
                  setSelected(
                    selectedIds.length === challengeLines.length
                      ? new Set()
                      : new Set(challengeLines.map((line) => line.line_id))
                  )
                }
              >
                {challengeLines.length &&
                selectedIds.length === challengeLines.length
                  ? "Clear selection"
                  : "Select all challenges"}
              </Button>
              <Button
                size="sm"
                disabled={!selectedIds.length || drafting}
                onClick={() => onDraftEmail(selectedIds)}
              >
                {drafting ? "Drafting…" : "Draft email"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div data-testid="analysis-table" className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8">
                    <span className="sr-only">Evidence</span>
                  </TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead className="text-right">
                    Third-party P90 (n)
                  </TableHead>
                  <TableHead className="text-right">Aviva DLG P90 (n)</TableHead>
                  <TableHead>Challenge level</TableHead>
                  <TableHead className="text-right">Challenge amount</TableHead>
                  <TableHead className="w-12">Select</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {lines.map((line) => {
                  const open = evidenceOpen.has(line.line_id)
                  const detailId = `analysis-evidence-${line.line_id}`
                  return (
                    <Fragment key={line.line_id}>
                      <TableRow
                        data-line-id={line.line_id}
                        data-level={line.challenge.level ?? "none"}
                        className={cn(
                          line.challenge.level === "low" &&
                            "bg-amber-50/60 dark:bg-amber-950/20"
                        )}
                      >
                        <TableCell>
                          <button
                            type="button"
                            onClick={() =>
                              toggleIn(setEvidenceOpen, line.line_id)
                            }
                            aria-expanded={open}
                            aria-controls={detailId}
                            aria-label={`${open ? "Hide" : "Show"} evidence for ${line.description}`}
                            className="text-muted-foreground transition-colors hover:text-foreground"
                          >
                            {open ? (
                              <ChevronDownIcon className="size-4" />
                            ) : (
                              <ChevronRightIcon className="size-4" />
                            )}
                          </button>
                        </TableCell>
                        <TableCell>
                          <span className="font-medium">{line.description}</span>
                          <span className="mt-1 flex flex-wrap items-center gap-1.5">
                            <OriginBadge origin={line.origin} />
                            {line.repair_item ? (
                              <span className="text-xs text-muted-foreground">
                                {line.repair_item}
                              </span>
                            ) : null}
                          </span>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {money(line.amount)}
                        </TableCell>
                        <BenchmarkCell benchmark={line.benchmarks.third_party} />
                        <BenchmarkCell benchmark={line.benchmarks.aviva_dlg} />
                        <TableCell>
                          <LevelBadge level={line.challenge.level} />
                        </TableCell>
                        <ChallengeAmountCell line={line} />
                        <TableCell>
                          {isChallenge(line) ? (
                            <Checkbox
                              checked={selected.has(line.line_id)}
                              onCheckedChange={(checked) =>
                                toggleIn(setSelected, line.line_id, checked === true)
                              }
                              aria-label={`Select ${line.description} for the challenge email`}
                            />
                          ) : null}
                        </TableCell>
                      </TableRow>
                      {open ? (
                        <TableRow id={detailId}>
                          <TableCell colSpan={8} className="bg-muted/30 p-3">
                            <p className="mb-3 text-sm">{line.challenge.reason}</p>
                            <div className="grid gap-4 xl:grid-cols-2">
                              {SOURCES.map((source) => (
                                <div key={source} className="min-w-0">
                                  <h4 className="mb-2 text-sm font-semibold">
                                    {BENCHMARK_SOURCES[source].label} evidence
                                  </h4>
                                  <EvidenceTable
                                    rows={line.benchmarks[source].evidence}
                                  />
                                </div>
                              ))}
                            </div>
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </Fragment>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* "Now we are able to combine them when we do the analysis." The
          split was taken out of the extract tables on 17 Sep and moved here:
          how each rolled-up invoice total breaks down into the engineer
          assessment rows that the lines above were benchmarked on. */}
      <Card>
        <CardHeader>
          <CardTitle>How each rolled-up invoice total breaks down</CardTitle>
          <CardDescription>
            A total the invoice prints as one figure is never benchmarked. Its
            line items come from the paired engineer assessment, and only when
            the section total agrees with the engineer assessment's.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {analysis.section_breakdowns.length ? (
            analysis.section_breakdowns.map((breakdown) => (
              <div key={breakdown.invoice_line_item_id}>
                <p className="mt-2 text-sm font-medium">
                  {breakdown.description}
                </p>
                <SectionBreakdownDetail breakdown={breakdown} />
              </div>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">
              This invoice prints no rolled-up totals: every invoice line above
              is itemised on the invoice itself.
            </p>
          )}
        </CardContent>
      </Card>
    </>
  )
}

/** The drafted email. It says it is a draft, and that nothing has been sent,
 * because nothing has: the server never sends it, and the only ways out of
 * here are the clipboard and the handler's own email app. */
export function ChallengeEmailDraftView({
  draft,
  onCopy,
}: {
  draft: ChallengeEmailDraft
  onCopy: (text: string) => void
}) {
  const text = `Subject: ${draft.subject}\n\n${draft.body}`
  return (
    <div className="flex flex-col gap-4">
      <Alert>
        <MailIcon />
        <AlertTitle>This is a draft. Nothing has been sent.</AlertTitle>
        <AlertDescription>
          ClaimGuard does not email anyone. Copy the draft, or open it in your
          email app, check it, and send it from there yourself.
        </AlertDescription>
      </Alert>
      <p className="text-xs text-muted-foreground">
        {generatedByLabel(draft.generated_by)} · total challenge amount in this
        draft {money(draft.total_challenge_amount)} across {draft.lines.length}{" "}
        {draft.lines.length === 1 ? "line" : "lines"}.
      </p>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        Subject
        <Input readOnly value={draft.subject} />
      </label>
      <label className="flex flex-col gap-1.5 text-sm font-medium">
        Body
        <Textarea readOnly value={draft.body} className="min-h-64 font-mono text-xs" />
      </label>
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="outline" onClick={() => onCopy(text)}>
          Copy
        </Button>
        <Button asChild>
          <a href={mailtoHref(draft.subject, draft.body)}>Open in email app</a>
        </Button>
      </div>
    </div>
  )
}

/** Benchmark analysis: the new invoice against both benchmarks, the
 * challenges, and the draft email. */
export function BenchmarkAnalysisScreen({
  caseReference,
  onUploadNewInvoice,
}: {
  caseReference: string
  onUploadNewInvoice: () => void
}) {
  const [invoiceId, setInvoiceId] = useState<string | undefined>(undefined)
  const [analysis, setAnalysis] = useState<BenchmarkAnalysisPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [drafting, setDrafting] = useState(false)
  const [draft, setDraft] = useState<ChallengeEmailDraft | null>(null)

  useEffect(() => {
    let active = true
    void fetchBenchmarkAnalysis(caseReference, invoiceId)
      .then((payload) => {
        if (!active) return
        setAnalysis(payload)
        setError(null)
      })
      .catch((e) => {
        if (!active) return
        setAnalysis(null)
        setError(documentApiErrorMessage(e))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [caseReference, invoiceId])

  async function draftEmail(lineIds: string[]) {
    if (!analysis || drafting) return
    setDrafting(true)
    try {
      setDraft(
        await draftChallengeEmail(caseReference, {
          invoiceId: analysis.invoice.id,
          lineIds,
        })
      )
    } catch (e) {
      toast.error("The email could not be drafted", {
        description: documentApiErrorMessage(e),
      })
    } finally {
      setDrafting(false)
    }
  }

  function copy(text: string) {
    void navigator.clipboard
      .writeText(text)
      .then(() =>
        toast.success("Draft copied", {
          description: "Nothing has been sent.",
        })
      )
      .catch(() => toast.error("The draft could not be copied"))
  }

  return (
    <>
      <ScreenHeading
        title="Benchmark analysis"
        description="Every line item of the new invoice -- from the invoice first, then from its engineer assessment -- against the third-party and the Aviva DLG P90 for its vehicle category. Red where a benchmark is violated."
      />
      {error ? (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>The analysis could not be loaded</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-3">
            <span>
              {error} If no new invoice has been uploaded yet, upload one
              first.
            </span>
            <Button variant="outline" size="sm" onClick={onUploadNewInvoice}>
              Upload new invoice
            </Button>
          </AlertDescription>
        </Alert>
      ) : loading || !analysis ? (
        <p className="text-sm text-muted-foreground">Loading the analysis…</p>
      ) : (
        <BenchmarkAnalysisView
          key={analysis.invoice.id}
          analysis={analysis}
          onSelectInvoice={(id) => {
            setLoading(true)
            setInvoiceId(id)
          }}
          onDraftEmail={(lineIds) => void draftEmail(lineIds)}
          drafting={drafting}
        />
      )}
      <Dialog
        open={draft != null}
        onOpenChange={(open) => {
          if (!open) setDraft(null)
        }}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Challenge email draft</DialogTitle>
            <DialogDescription>
              For invoice {analysis?.invoice.invoice_number ?? ""}. Every £
              figure comes from the analysis.
            </DialogDescription>
          </DialogHeader>
          {draft ? <ChallengeEmailDraftView draft={draft} onCopy={copy} /> : null}
        </DialogContent>
      </Dialog>
    </>
  )
}
