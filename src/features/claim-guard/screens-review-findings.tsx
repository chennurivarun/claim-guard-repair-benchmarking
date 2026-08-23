import { useEffect, useState } from "react"
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  CheckIcon,
  EyeIcon,
  ExternalLinkIcon,
  InfoIcon,
  PencilLineIcon,
  SearchIcon,
  XIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "@/components/ui/input-group"
import { Separator } from "@/components/ui/separator"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { CalculationBreakdown } from "./calculation-breakdown"
import {
  ChallengeDecisionDialog,
  InlineMappingApproval,
  LineEvidenceSheet,
  type ResearchFormValues,
} from "./screens-challenge-admin"
import { formatMoney } from "./format"
import { documentImageUrl } from "./document-api"
import { isMappingApproved } from "./mapping-rules"
import { StatusBadge } from "./shared"
import type { ClaimWorkspace, InvoiceLine } from "./types"
import {
  fetchEngineerAssessments,
  type EngineerAssessmentPayload,
  type MappingDecisionInput,
} from "@/lib/api"

type DecisionMode = "approve" | "reject" | "edit"

function EngineerAssessmentCard({
  assessment,
}: {
  assessment: EngineerAssessmentPayload | null
}) {
  if (!assessment) return null
  const variances = assessment.operations.flatMap((operation) =>
    operation.variances.map((variance) => ({ operation, variance }))
  )
  return (
    <Card className="border-sky-200 bg-sky-50/40 dark:border-sky-950 dark:bg-sky-950/10">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Engineer assessment evidence</CardTitle>
            <CardDescription>
              {assessment.assessment_number ?? "Assessment"} is paired to this
              invoice using{" "}
              {assessment.pair_reasons.join(" and ") || "governed identifiers"}.
            </CardDescription>
          </div>
          <Badge variant="outline">
            {Math.round((assessment.pair_confidence ?? 0) * 100)}% pairing
            confidence
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border bg-background p-3">
            <p className="text-xs text-muted-foreground">Assessment total</p>
            <p className="mt-1 text-lg font-semibold tabular-nums">
              {formatMoney(Number(assessment.totals.gross_total ?? 0))}
            </p>
          </div>
          <div className="rounded-lg border bg-background p-3">
            <p className="text-xs text-muted-foreground">
              Operations extracted
            </p>
            <p className="mt-1 text-lg font-semibold">
              {assessment.operations.length}
            </p>
          </div>
          <div className="rounded-lg border bg-background p-3">
            <p className="text-xs text-muted-foreground">Comparable lines</p>
            <p className="mt-1 text-lg font-semibold">{variances.length}</p>
          </div>
        </div>
        <Alert>
          <InfoIcon />
          <AlertTitle>Separate evidence stream</AlertTitle>
          <AlertDescription>
            Engineer values are shown beside invoice variances only. They are
            not inserted into the historical invoice P90 population.
          </AlertDescription>
        </Alert>
        {variances.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border bg-background">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Engineer operation</TableHead>
                  <TableHead className="text-right">Engineer</TableHead>
                  <TableHead className="text-right">Invoice</TableHead>
                  <TableHead className="text-right">Variance</TableHead>
                  <TableHead>Engineer gate</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {variances.map(({ operation, variance }) => (
                  <TableRow
                    key={`${operation.id}-${variance.invoice_line_item_id}`}
                  >
                    <TableCell>
                      <p className="font-medium">{operation.description}</p>
                      <p className="text-xs text-muted-foreground">
                        {operation.code ?? operation.category}
                      </p>
                      {operation.source_page_id ? (
                        <a
                          href={documentImageUrl(
                            `/api/v1/pages/${operation.source_page_id}/image`
                          )}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-sky-700 hover:underline dark:text-sky-300"
                        >
                          Source page <ExternalLinkIcon className="size-3" />
                        </a>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMoney(Number(variance.engineer_amount ?? 0))}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMoney(Number(variance.invoice_amount ?? 0))}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMoney(Number(variance.difference_amount ?? 0))}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={
                          variance.threshold_status === "within_threshold"
                            ? "border-emerald-300 text-emerald-700"
                            : "border-red-300 text-red-700"
                        }
                      >
                        {variance.threshold_status === "within_threshold"
                          ? "Within threshold"
                          : variance.threshold_status === "above_10_percent"
                            ? "Above 10% + £5"
                            : "Above 5% + £5"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function InvoiceComparisonTable({
  rows,
  query,
  onQueryChange,
  onViewEvidence,
  onInspect,
}: {
  rows: InvoiceLine[]
  query: string
  onQueryChange: (value: string) => void
  onViewEvidence: (line: InvoiceLine) => void
  onInspect: (line: InvoiceLine) => void
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Challenged invoice items</CardTitle>
        <CardDescription>
          Review only lines with a positive challenge. Benchmark and external
          prices remain separate and traceable.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <InputGroup className="mb-4 max-w-md">
          <InputGroupAddon>
            <SearchIcon />
          </InputGroupAddon>
          <InputGroupInput
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Search invoice lines"
            aria-label="Search invoice lines"
          />
        </InputGroup>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Line</TableHead>
                <TableHead className="text-right">Billed</TableHead>
                <TableHead className="text-right">
                  Supported net price
                </TableHead>
                <TableHead className="text-right">P90 benchmark</TableHead>
                <TableHead className="text-right">Status</TableHead>
                <TableHead className="w-24">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-medium">
                    {item.description}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(item.currentTotal)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {item.recommended != null
                      ? formatMoney(item.recommended)
                      : "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {item.p90Benchmark
                      ? formatMoney(item.p90Benchmark.p90)
                      : "—"}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end">
                      <StatusBadge status={item.comparisonStatus} />
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => onViewEvidence(item)}
                        aria-label={`View evidence for ${item.description}`}
                      >
                        <EyeIcon />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => onInspect(item)}
                        aria-label={`Edit ${item.description}`}
                      >
                        <PencilLineIcon />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

export function ReviewFindingsScreen({
  workspace,
  p90ThresholdPct,
  enabled,
  processing,
  onDecision,
  onInspect,
  onContinue,
  onMappingDecision,
  mappingSavingLineId,
  onProposeNewItem,
  researchSaving,
}: {
  workspace: ClaimWorkspace
  p90ThresholdPct: number
  enabled: boolean
  processing: boolean
  onDecision: (
    line: InvoiceLine,
    decision: {
      approved: boolean
      rationale: string
      challengePriceNet?: number
    }
  ) => Promise<void>
  onInspect: (line: InvoiceLine) => void
  onContinue: () => void
  onMappingDecision?: (
    line: InvoiceLine,
    input: Omit<MappingDecisionInput, "actor">
  ) => Promise<void>
  mappingSavingLineId?: string | null
  onProposeNewItem?: (
    line: InvoiceLine,
    values: ResearchFormValues
  ) => Promise<void>
  researchSaving?: boolean
}) {
  const ontologyOptions = workspace.ontologyBank?.items ?? []
  const challenged = workspace.lines
    .filter((line) => line.challenge > 0)
    .sort((a, b) => b.challenge - a.challenge)
  const [activeIndex, setActiveIndex] = useState(0)
  const [query, setQuery] = useState("")
  const [evidenceLine, setEvidenceLine] = useState<InvoiceLine | null>(null)
  const [decisionLine, setDecisionLine] = useState<InvoiceLine | null>(null)
  const [decisionMode, setDecisionMode] = useState<DecisionMode | null>(null)
  const [engineerAssessment, setEngineerAssessment] =
    useState<EngineerAssessmentPayload | null>(null)
  useEffect(() => {
    let cancelled = false
    fetchEngineerAssessments(workspace.claim.id)
      .then((assessments) => {
        if (cancelled) return
        setEngineerAssessment(
          assessments.find(
            (assessment) =>
              assessment.pair_status === "paired" &&
              assessment.paired_invoice_id === workspace.invoice.id
          ) ?? null
        )
      })
      .catch(() => {
        if (!cancelled) setEngineerAssessment(null)
      })
    return () => {
      cancelled = true
    }
  }, [workspace.claim.id, workspace.invoice.id])
  const line =
    challenged[Math.min(activeIndex, Math.max(challenged.length - 1, 0))]
  const unresolved = challenged.filter(
    (item) =>
      !["approved", "rejected"].includes(item.challengeStatus ?? "review")
  )
  const rows = challenged.filter((item) =>
    item.description.toLowerCase().includes(query.toLowerCase())
  )

  if (!line) {
    return (
      <>
        <div>
          <p className="text-sm font-medium text-muted-foreground">
            Claim {workspace.claim.id}
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">
            Review findings - challenged invoices
          </h1>
        </div>
        <EngineerAssessmentCard assessment={engineerAssessment} />
        <Alert>
          <CheckIcon />
          <AlertTitle>No price challenges found</AlertTitle>
          <AlertDescription>
            The invoice is within the current policy and P90 thresholds.
          </AlertDescription>
        </Alert>
        <InvoiceComparisonTable
          rows={rows}
          query={query}
          onQueryChange={setQuery}
          onViewEvidence={setEvidenceLine}
          onInspect={onInspect}
        />
        <LineEvidenceSheet
          line={evidenceLine}
          p90ThresholdPct={p90ThresholdPct}
          onClose={() => setEvidenceLine(null)}
          ontologyOptions={ontologyOptions}
          mappingSaving={mappingSavingLineId === evidenceLine?.id}
          onMappingDecision={onMappingDecision}
          researchSaving={researchSaving}
          onProposeNewItem={onProposeNewItem}
        />
      </>
    )
  }

  const approved = line.challengeStatus === "approved"
  const rejected = line.challengeStatus === "rejected"
  const mappingApproved = isMappingApproved(line)
  const benchmark = line.p90Benchmark
  const benchmarkChallenged = Boolean(benchmark && line.challenge > 0)

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Review findings - challenged invoices
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Decide whether the evidence supports this price challenge.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">
            {activeIndex + 1} of {challenged.length}
          </Badge>
          {!mappingApproved ? (
            <Badge variant="warning">Provisional mapping</Badge>
          ) : null}
          <StatusBadge status={line.challengeStatus ?? "review"} />
        </div>
      </div>

      <EngineerAssessmentCard assessment={engineerAssessment} />

      {!mappingApproved ? (
        <div className="flex flex-col gap-3">
          <Alert>
            <InfoIcon />
            <AlertTitle>
              Provisional finding: repair item match needs approval
            </AlertTitle>
            <AlertDescription>
              Approve, change, or propose a new repair item match below before
              making a challenge decision. The price evidence remains visible
              for review, but it is not yet actionable.
            </AlertDescription>
          </Alert>
          {onMappingDecision ? (
            <InlineMappingApproval
              line={line}
              ontologyOptions={ontologyOptions}
              mappingSaving={mappingSavingLineId === line.id}
              onMappingDecision={onMappingDecision}
              researchSaving={researchSaving}
              onProposeNewItem={onProposeNewItem}
            />
          ) : null}
        </div>
      ) : null}

      <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <CardDescription>Invoice line</CardDescription>
                <CardTitle className="mt-1 text-xl">
                  {line.description}
                </CardTitle>
                <p className="mt-2 text-sm text-muted-foreground">
                  {line.quantity} {line.unit} · {line.kind}
                </p>
              </div>
              <Badge variant="destructive">
                {formatMoney(line.challenge)} high
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            <div className="grid overflow-hidden rounded-lg border sm:grid-cols-4">
              <div className="p-5">
                <p className="text-xs font-medium text-muted-foreground">
                  Repairer billed
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {formatMoney(line.currentTotal)}
                </p>
              </div>
              <div className="border-y p-5 sm:border-x sm:border-y-0">
                <p className="text-xs font-medium text-muted-foreground">
                  Benchmark price
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {benchmark ? formatMoney(benchmark.p90) : "—"}
                </p>
              </div>
              <div className="border-b p-5 sm:border-r sm:border-b-0">
                <p className="text-xs font-medium text-muted-foreground">
                  External price
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {line.ontologyTotal ? formatMoney(line.ontologyTotal) : "—"}
                </p>
              </div>
              <div className="bg-primary/5 p-5">
                <p className="text-xs font-medium text-muted-foreground">
                  Challenge amount
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {formatMoney(line.challenge)}
                </p>
              </div>
            </div>

            {benchmark ? (
              <div className="rounded-lg border bg-muted/25 p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="font-semibold">Historical P90 benchmark</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {benchmark.category} · {benchmark.historicalCount} earlier
                      invoice{benchmark.historicalCount === 1 ? "" : "s"} ·
                      based only on earlier invoices
                    </p>
                  </div>
                  <Badge
                    variant={benchmarkChallenged ? "destructive" : "outline"}
                  >
                    {benchmarkChallenged
                      ? "Above P90 threshold"
                      : "Within P90 threshold"}
                  </Badge>
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  <div>
                    <p className="text-xs text-muted-foreground">
                      Current charge
                    </p>
                    <p className="mt-1 font-semibold tabular-nums">
                      {formatMoney(benchmark.currentPrice)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">
                      P90 benchmark
                    </p>
                    <p className="mt-1 font-semibold tabular-nums">
                      {formatMoney(benchmark.p90)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Difference</p>
                    <p
                      className={`mt-1 font-semibold tabular-nums ${
                        benchmarkChallenged ? "text-destructive" : ""
                      }`}
                    >
                      {benchmark.difference > 0 ? "+" : ""}
                      {formatMoney(benchmark.difference)} ·{" "}
                      {benchmark.percentageDifference > 0 ? "+" : ""}
                      {benchmark.percentageDifference.toFixed(1)}%
                    </p>
                  </div>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="mt-3"
                  onClick={() => setEvidenceLine(line)}
                >
                  <EyeIcon data-icon="inline-start" />
                  View {benchmark.historicalCount} prices used
                </Button>
              </div>
            ) : (
              <Alert>
                <InfoIcon />
                <AlertTitle>P90 benchmark not available yet</AlertTitle>
                <AlertDescription>
                  At least three earlier matching invoice prices are required.
                  The existing governed price evidence is shown below.
                </AlertDescription>
              </Alert>
            )}

            <div>
              <h2 className="text-sm font-semibold">Why it was flagged</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {line.rationale}
              </p>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                When both prices are available, the supported price uses 70%
                benchmark and 30% approved external price. If only one is
                available, that available price is used.
              </p>
            </div>

            <div>
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold">Evidence used</h2>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setEvidenceLine(line)}
                >
                  <EyeIcon data-icon="inline-start" />
                  View details
                </Button>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                {(line.ontologyTotal ?? 0) > 0 ? (
                  <div className="rounded-lg border p-4">
                    <p className="text-xs font-medium text-muted-foreground">
                      Approved price bank
                    </p>
                    <p className="mt-2 text-lg font-semibold tabular-nums">
                      {formatMoney(line.ontologyTotal)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {line.ontologyName ??
                        line.ontologyId ??
                        "Approved ontology item"}
                    </p>
                  </div>
                ) : null}
                <div className="rounded-lg border p-4">
                  <p className="text-xs font-medium text-muted-foreground">
                    Historical claims median
                  </p>
                  <p className="mt-2 text-lg font-semibold tabular-nums">
                    {formatMoney(line.historicalMedian)}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Median of {line.historicalCount} governed comparable records
                  </p>
                </div>
                {benchmark ? (
                  <div className="rounded-lg border p-4">
                    <p className="text-xs font-medium text-muted-foreground">
                      Uploaded-invoice P90
                    </p>
                    <p className="mt-2 text-lg font-semibold tabular-nums">
                      {formatMoney(benchmark.p90)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {benchmark.historicalCount} earlier uploaded invoices; the
                      current invoice is not counted
                    </p>
                  </div>
                ) : null}
              </div>
            </div>

            <Alert>
              <InfoIcon />
              <AlertTitle>How the price was calculated</AlertTitle>
              <AlertDescription>
                {line.evidenceRationale ??
                  "The supported net price uses the persisted ontology and historical claim evidence. VAT is handled separately."}
              </AlertDescription>
            </Alert>
            <CalculationBreakdown steps={line.calculation} />
          </CardContent>
          <CardFooter className="flex-col items-stretch gap-3 border-t pt-6">
            <Button
              size="lg"
              disabled={!enabled || processing || approved || !mappingApproved}
              onClick={() =>
                void onDecision(line, {
                  approved: true,
                  challengePriceNet: line.recommended,
                  rationale:
                    "Accepted after reviewing the historical P90 benchmark and its earlier invoice evidence.",
                })
              }
            >
              <CheckIcon data-icon="inline-start" />
              {approved
                ? "Challenge accepted"
                : !mappingApproved
                  ? "Approve repair item match first"
                  : `Accept supported price · ${formatMoney(line.recommended)}`}
            </Button>
            <div className="grid gap-2 sm:grid-cols-2">
              <Button
                variant="outline"
                disabled={!enabled || processing || !mappingApproved}
                onClick={() => {
                  setDecisionLine(line)
                  setDecisionMode("edit")
                }}
              >
                <PencilLineIcon data-icon="inline-start" />
                Adjust supported price
              </Button>
              <Button
                variant="ghost"
                disabled={
                  !enabled || processing || rejected || !mappingApproved
                }
                onClick={() => {
                  setDecisionLine(line)
                  setDecisionMode("reject")
                }}
              >
                <XIcon data-icon="inline-start" />
                Do not challenge
              </Button>
            </div>
          </CardFooter>
        </Card>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Decision context</CardTitle>
              <CardDescription>
                The impact of accepting this finding.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4 text-sm">
              {[
                ["Invoice", workspace.invoice.number],
                ["Repairer", workspace.invoice.garage],
                ["Line reduction", formatMoney(line.challenge)],
                ["VAT impact", formatMoney(line.challengeVat)],
                ["Evidence strength", `${line.challengeStrength ?? 0}/100`],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="flex items-start justify-between gap-4"
                >
                  <span className="text-muted-foreground">{label}</span>
                  <span className="text-right font-medium tabular-nums">
                    {value}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Review progress</CardTitle>
              <CardDescription>
                {unresolved.length} decision{unresolved.length === 1 ? "" : "s"}{" "}
                remaining.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex items-center justify-between gap-2">
              <Button
                variant="outline"
                size="icon"
                disabled={activeIndex === 0}
                onClick={() => setActiveIndex((value) => value - 1)}
                aria-label="Previous finding"
              >
                <ArrowLeftIcon />
              </Button>
              <span className="text-sm text-muted-foreground">
                {activeIndex + 1} / {challenged.length}
              </span>
              <Button
                variant="outline"
                size="icon"
                disabled={activeIndex === challenged.length - 1}
                onClick={() => setActiveIndex((value) => value + 1)}
                aria-label="Next finding"
              >
                <ArrowRightIcon />
              </Button>
            </CardContent>
            <CardFooter>
              <Button variant="outline" className="w-full" onClick={onContinue}>
                Go to approval
                <ArrowRightIcon data-icon="inline-end" />
              </Button>
            </CardFooter>
          </Card>
        </div>
      </div>

      <InvoiceComparisonTable
        rows={rows}
        query={query}
        onQueryChange={setQuery}
        onViewEvidence={setEvidenceLine}
        onInspect={onInspect}
      />

      <Separator />
      <p className="text-center text-xs text-muted-foreground">
        Policy {workspace.versions?.policy ?? "v1.4"} · Net line totals · £5 /
        {p90ThresholdPct}% gates
      </p>

      <LineEvidenceSheet
        line={evidenceLine}
        p90ThresholdPct={p90ThresholdPct}
        onClose={() => setEvidenceLine(null)}
        ontologyOptions={ontologyOptions}
        mappingSaving={mappingSavingLineId === evidenceLine?.id}
        onMappingDecision={onMappingDecision}
        researchSaving={researchSaving}
        onProposeNewItem={onProposeNewItem}
      />
      <ChallengeDecisionDialog
        key={`${decisionLine?.id ?? "closed"}-${decisionMode ?? "none"}`}
        line={decisionLine}
        mode={decisionMode}
        saving={processing}
        onClose={() => {
          setDecisionLine(null)
          setDecisionMode(null)
        }}
        onSubmit={async (decision) => {
          if (!decisionLine) return
          await onDecision(decisionLine, decision)
          setDecisionLine(null)
          setDecisionMode(null)
        }}
      />
    </>
  )
}
