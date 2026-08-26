import { useEffect, useState } from "react"
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  CheckIcon,
  DownloadIcon,
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
  inHouseRepairCsvUrl,
  type EngineerAssessmentPayload,
  type ClaimInvoiceSummary,
  type MappingDecisionInput,
} from "@/lib/api"

type DecisionMode = "approve" | "reject" | "edit"

export function ChallengedInvoicesSummary({
  invoices,
  onOpenInvoice,
}: {
  invoices: ClaimInvoiceSummary[]
  onOpenInvoice: (invoiceId: string, lineId: string | null) => void
}) {
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState("all")
  const [invoiceFilter, setInvoiceFilter] = useState("all")
  const [lineFilter, setLineFilter] = useState("all")
  const [dateFrom, setDateFrom] = useState("")
  const [dateTo, setDateTo] = useState("")
  const needle = query.trim().toLocaleLowerCase()
  const invoiceChoices = invoices.map((invoice) => ({
    id: invoice.id,
    label: invoice.invoice_number || invoice.document_filename,
  }))
  const lineChoices = Array.from(
    new Set(
      invoices.flatMap((invoice) =>
        (invoice.challenge_lines ?? [])
          .map((line) => line.description?.trim())
          .filter((value): value is string => Boolean(value))
      )
    )
  ).sort((left, right) => left.localeCompare(right))
  const rows = invoices
    .flatMap((invoice) =>
      (invoice.challenge_lines ?? []).map((line) => ({ invoice, line }))
    )
    .filter(({ invoice, line }) => {
      const lineStatus = line.status.toLocaleLowerCase()
      const invoiceDate = (invoice.invoice_date ?? "").slice(0, 10)
      const matchesStatus =
        status === "all" ||
        lineStatus === status ||
        (status === "pending" && ["draft", "review"].includes(lineStatus))
      const searchable = [
        invoice.invoice_number,
        invoice.document_filename,
        invoice.supplier_name,
        line.description,
      ]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase()
      return (
        matchesStatus &&
        (invoiceFilter === "all" || invoice.id === invoiceFilter) &&
        (lineFilter === "all" || line.description === lineFilter) &&
        (!dateFrom || invoiceDate >= dateFrom) &&
        (!dateTo || invoiceDate <= dateTo) &&
        (!needle || searchable.includes(needle))
      )
    })
    .sort(
      (left, right) =>
        right.line.challenge_net - left.line.challenge_net ||
        Date.parse(right.invoice.uploaded_at ?? "") -
          Date.parse(left.invoice.uploaded_at ?? "")
    )

  return (
    <Card>
      <CardHeader>
        <CardTitle>Challenged invoices</CardTitle>
        <CardDescription>
          Only invoice lines with a positive price challenge are shown. Select a
          row to open the existing evidence and decision flow.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
          <InputGroup className="max-w-md">
            <InputGroupAddon>
              <SearchIcon />
            </InputGroupAddon>
            <InputGroupInput
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search challenged invoices"
              aria-label="Search challenged invoices"
            />
          </InputGroup>
          <select
            className="h-9 rounded-md border bg-background px-3 text-sm"
            value={invoiceFilter}
            onChange={(event) => setInvoiceFilter(event.target.value)}
            aria-label="Filter by invoice"
          >
            <option value="all">All invoices</option>
            {invoiceChoices.map((invoice) => (
              <option key={invoice.id} value={invoice.id}>
                {invoice.label}
              </option>
            ))}
          </select>
          <select
            className="h-9 rounded-md border bg-background px-3 text-sm"
            value={lineFilter}
            onChange={(event) => setLineFilter(event.target.value)}
            aria-label="Filter by challenged item"
          >
            <option value="all">All repair items</option>
            {lineChoices.map((description) => (
              <option key={description} value={description}>
                {description}
              </option>
            ))}
          </select>
          <input
            type="date"
            className="h-9 rounded-md border bg-background px-3 text-sm"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
            aria-label="Invoice date from"
          />
          <input
            type="date"
            className="h-9 rounded-md border bg-background px-3 text-sm"
            value={dateTo}
            onChange={(event) => setDateTo(event.target.value)}
            aria-label="Invoice date to"
          />
          <select
            className="h-9 rounded-md border bg-background px-3 text-sm"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            aria-label="Filter challenge status"
          >
            <option value="all">All statuses</option>
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-right">Challenge amount</TableHead>
                <TableHead>Repair item</TableHead>
                <TableHead className="text-right">Billed price</TableHead>
                <TableHead className="text-right">
                  In-house benchmark P90
                </TableHead>
                <TableHead className="text-right">
                  Historical claims P90
                </TableHead>
                <TableHead className="text-right">
                  External reference price
                </TableHead>
                <TableHead className="text-right">Supported price</TableHead>
                <TableHead>Invoice</TableHead>
                <TableHead>Repairer</TableHead>
                <TableHead>Invoice date</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(({ invoice, line }) => (
                <TableRow
                  key={`${invoice.id}:${line.line_id ?? line.id}`}
                  className="cursor-pointer"
                  tabIndex={0}
                  onClick={() =>
                    onOpenInvoice(invoice.id, line.line_id ?? line.id)
                  }
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault()
                      onOpenInvoice(invoice.id, line.line_id ?? line.id)
                    }
                  }}
                >
                  <TableCell className="text-right font-semibold text-destructive tabular-nums">
                    {formatMoney(line.challenge_net)}
                  </TableCell>
                  <TableCell>{line.description || "Unlabelled line"}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(line.billed_net)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {line.in_house_p90_net == null
                      ? "—"
                      : formatMoney(line.in_house_p90_net)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {line.historical_claims_p90_net == null
                      ? "—"
                      : formatMoney(line.historical_claims_p90_net)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {line.external_price_net == null
                      ? "—"
                      : formatMoney(line.external_price_net)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(line.supported_net)}
                  </TableCell>
                  <TableCell>
                    <span className="block font-medium">
                      {invoice.invoice_number || invoice.document_filename}
                    </span>
                    {invoice.vehicle?.make || invoice.vehicle?.model ? (
                      <span className="block text-xs text-muted-foreground">
                        {[invoice.vehicle.make, invoice.vehicle.model]
                          .filter(Boolean)
                          .join(" ")}
                        {invoice.vehicle.registration
                          ? ` · ${invoice.vehicle.registration}`
                          : ""}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell>{invoice.supplier_name || "—"}</TableCell>
                  <TableCell className="text-xs whitespace-nowrap text-muted-foreground">
                    {invoice.invoice_date
                      ? new Date(
                          `${invoice.invoice_date}T00:00:00`
                        ).toLocaleDateString()
                      : "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {line.status.replaceAll("_", " ")}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
              {!rows.length ? (
                <TableRow>
                  <TableCell
                    colSpan={11}
                    className="py-8 text-center text-muted-foreground"
                  >
                    No challenged invoice lines match these filters.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

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

function AllExtractedLinesTable({ lines }: { lines: InvoiceLine[] }) {
  if (!lines.length) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle>All extracted lines ({lines.length})</CardTitle>
        <CardDescription>
          Every line read from this invoice, including parts and charges that
          are within thresholds or still awaiting a repair-item match.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Line</TableHead>
                <TableHead>Part number</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Billed net</TableHead>
                <TableHead>Repair item match</TableHead>
                <TableHead className="text-right">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {lines.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-medium">
                    {item.description}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {item.partNumber || "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {item.quantity} {item.unit}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(item.currentTotal)}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {item.ontologyId
                      ? isMappingApproved(item)
                        ? "Matched"
                        : "Match awaiting approval"
                      : "No match — proposal in Manual review"}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end">
                      <StatusBadge
                        status={
                          item.challenge > 0 ? item.comparisonStatus : "WITHIN"
                        }
                      />
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
  mode = "challenged",
  initialLineId = null,
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
  mode?: "challenged" | "all"
  initialLineId?: string | null
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
  const requestedInitialIndex = initialLineId
    ? challenged.findIndex((item) => item.id === initialLineId)
    : -1
  const [activeIndex, setActiveIndex] = useState(() =>
    requestedInitialIndex >= 0 ? requestedInitialIndex : 0
  )
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

  if (mode === "all") {
    return (
      <>
        <div>
          <p className="text-sm font-medium text-muted-foreground">
            Claim {workspace.claim.id}
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">
            Review findings - all extracted lines
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Every scanned invoice and extracted line is available here,
            including lines with no price challenge.
          </p>
        </div>
        <EngineerAssessmentCard assessment={engineerAssessment} />
        <Alert>
          <InfoIcon />
          <AlertTitle>
            {challenged.length} challenged line
            {challenged.length === 1 ? "" : "s"} in this invoice
          </AlertTitle>
          <AlertDescription>
            Use Challenged invoices for decisions. This advanced view is the
            full extraction record.
          </AlertDescription>
        </Alert>
        <AllExtractedLinesTable lines={workspace.lines} />
      </>
    )
  }

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
          <StatusBadge status={line.challengeStatus ?? "review"} />
        </div>
      </div>

      <EngineerAssessmentCard assessment={engineerAssessment} />

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
                <p className="mt-1 text-sm text-muted-foreground">
                  {workspace.invoice.vehicle || "Vehicle not recorded"}
                  {workspace.invoice.vrm ? ` · ${workspace.invoice.vrm}` : ""}
                </p>
              </div>
              <Badge variant="destructive">
                {formatMoney(line.challenge)} high
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            <div className="grid overflow-hidden rounded-lg border md:grid-cols-3 2xl:grid-cols-6">
              <div className="bg-primary/5 p-5">
                <p className="text-xs font-medium text-muted-foreground">
                  Challenge amount
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {formatMoney(line.challenge)}
                </p>
              </div>
              <div className="border-y p-5 md:border-x md:border-y-0">
                <p className="text-xs font-medium text-muted-foreground">
                  Billed price
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {formatMoney(line.currentTotal)}
                </p>
              </div>
              <div className="border-b p-5 md:border-b-0 2xl:border-r">
                <p className="text-xs font-medium text-muted-foreground">
                  In-house benchmark P90
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {line.inHouseP90 == null ? "—" : formatMoney(line.inHouseP90)}
                </p>
              </div>
              <div className="border-b p-5 md:border-r 2xl:border-b-0">
                <p className="text-xs font-medium text-muted-foreground">
                  Historical claims P90
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {line.historicalClaimsP90 == null
                    ? "—"
                    : formatMoney(line.historicalClaimsP90)}
                </p>
              </div>
              <div className="border-b p-5 md:border-b-0 2xl:border-r">
                <p className="text-xs font-medium text-muted-foreground">
                  External reference price
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {line.externalReferencePrice == null
                    ? "—"
                    : formatMoney(line.externalReferencePrice)}
                </p>
              </div>
              <div className="p-5">
                <p className="text-xs font-medium text-muted-foreground">
                  Supported price
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">
                  {line.recommended == null
                    ? "—"
                    : formatMoney(line.recommended)}
                </p>
              </div>
            </div>

            <div>
              <h2 className="text-sm font-semibold">
                Why this price challenge is recommended
              </h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {line.rationale}
              </p>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                The full policy uses 50% in-house benchmark P90, 30% historical
                claims P90 and 20% external reference price. Missing governed
                sources contribute zero and the result is divided by the sum of
                the source weights that are available.
              </p>
            </div>

            <Card className="bg-muted/20">
              <CardHeader>
                <CardTitle className="text-base">Evidence used</CardTitle>
                <CardDescription>
                  The source file supporting this line&apos;s in-house benchmark.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-col gap-4 rounded-lg border bg-background p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-sm font-medium">In-house P90</p>
                    <p className="mt-1 text-xl font-semibold tabular-nums">
                      {line.inHouseP90 == null
                        ? "Not available"
                        : formatMoney(line.inHouseP90)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Calculated from the active in-house repair dataset.
                    </p>
                  </div>
                  <Button asChild variant="outline" size="sm">
                    <a
                      href={inHouseRepairCsvUrl()}
                      download="claim-guard-in-house-repair-data.csv"
                    >
                      <DownloadIcon data-icon="inline-start" />
                      Download source CSV
                    </a>
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Alert>
              <InfoIcon />
              <AlertTitle>How the price was calculated</AlertTitle>
              <AlertDescription className="space-y-3">
                <p>
                  {line.evidenceRationale ??
                    "Supported price is the weighted average of the available sources: 50% in-house benchmark P90, 30% historical claims P90 and 20% external reference price. Missing sources contribute zero and their weights are excluded from the denominator."}
                </p>
              </AlertDescription>
            </Alert>
            <CalculationBreakdown steps={line.calculation} />
          </CardContent>
          <CardFooter className="flex-col items-stretch gap-3 border-t pt-6">
            <Button
              size="lg"
              disabled={!enabled || processing || approved}
              onClick={() =>
                void onDecision(line, {
                  approved: true,
                  rationale:
                    "Accepted after reviewing the supported price and its in-house, historical-claims, and external-reference evidence.",
                })
              }
            >
              <CheckIcon data-icon="inline-start" />
              {approved
                ? "Challenge accepted"
                : `Accept supported price · ${formatMoney(line.recommended)}`}
            </Button>
            <div className="grid gap-2 sm:grid-cols-2">
              <Button
                variant="outline"
                disabled={!enabled || processing}
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
                disabled={!enabled || processing || rejected}
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
