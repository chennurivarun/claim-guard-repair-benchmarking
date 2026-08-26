import { useEffect, useMemo, useRef, useState } from "react"
import {
  AlertCircleIcon,
  ArrowRightIcon,
  BadgeCheckIcon,
  BanknoteIcon,
  CheckCheckIcon,
  CheckIcon,
  DatabaseIcon,
  DownloadIcon,
  EyeIcon,
  ExternalLinkIcon,
  FileJson2Icon,
  FileSpreadsheetIcon,
  FileTextIcon,
  FlaskConicalIcon,
  InfoIcon,
  PencilLineIcon,
  PlusIcon,
  SearchIcon,
  ShieldCheckIcon,
  XCircleIcon,
} from "lucide-react"
import { toast } from "sonner"
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
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "@/components/ui/input-group"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"

import { CalculationBreakdown } from "./calculation-breakdown"
import { auditEvents, ontologyVersions } from "./demo-data"
import { DocumentBriefingButton } from "./document-briefing"
import {
  documentApiErrorMessage,
  documentImageUrl,
  fetchCaseDocuments,
  fetchDocumentPages,
  type DocumentPageRecord,
  type UploadedDocument,
} from "./document-api"
import { formatMoney } from "./format"
import { downloadManualReviewCsv } from "./manual-review-export"
import { isMappingApproved } from "./mapping-rules"
import {
  MappingDecisionDialog,
  type MappingDialogSelection,
} from "./screens-validation"
import {
  ConfidenceCell,
  DataCard,
  Metric,
  MINIMUM_CHALLENGE_AMOUNT,
  ScreenHeading,
  StatusBadge,
} from "./shared"
import {
  addManualInvoiceLine,
  fetchClaimInvoices,
  fetchHistoricalObservation,
  getApiErrorMessage,
  type ClaimInvoiceSummary,
  type HistoricalObservationPayload,
  type MappingDecisionInput,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import type {
  ClaimWorkspace,
  InvoiceLine,
  OntologyBankItem,
  PriceObservationRecord,
  ResearchQueueItem,
} from "./types"

function ChallengeSummary({ workspace }: { workspace: ClaimWorkspace }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardDescription>Proposed payable net</CardDescription>
            <CardTitle className="mt-1 text-3xl tabular-nums">
              {formatMoney(workspace.summary.challengePrice)}
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              Proposed payable · net, including £54.85 non-VAT MOT
            </p>
          </div>
          <Badge variant="success">
            {workspace.summary.challengeStrength} / 100 · STRONG
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 border-t pt-5 sm:grid-cols-2 xl:grid-cols-5">
          <Metric
            label="Original net"
            value={formatMoney(workspace.invoice.netIncludingMot)}
            hint="MOT included"
          />
          <Metric
            label="Challenge amount"
            value={formatMoney(workspace.summary.challengeAmount)}
            hint={`${workspace.summary.challengePercentage}% of net invoice`}
            emphasis
          />
          <Metric
            label="VAT impact"
            value={formatMoney(workspace.summary.vatImpact)}
            hint="Shown separately"
          />
          <Metric
            label="Gross cash effect"
            value={formatMoney(workspace.summary.grossEffect)}
            hint="Net + VAT impact"
          />
          <Metric label="Policy" value="60 / 40" hint="Ontology / historic" />
        </div>
      </CardContent>
    </Card>
  )
}

function comparisonLabel(status: InvoiceLine["comparisonStatus"]) {
  if (status === "CHALLENGE") return "CHALLENGE"
  if (status === "BELOW_GATE") return "BELOW £5 GATE"
  if (status === "MISSING") return "NO APPROVED PRICE"
  return "WITHIN"
}

function differenceLabel(value?: number | null) {
  if (value === undefined || value === null) return "Difference —"
  const sign = value > 0 ? "+" : value < 0 ? "−" : ""
  return `Difference ${sign}${formatMoney(Math.abs(value))}`
}

const HISTORICAL_OBSERVATION_PATH_PREFIX = "/api/v1/historical-observations/"

function HistoricalObservationDialog({
  observationId,
  onClose,
}: {
  observationId: string | null
  onClose: () => void
}) {
  const [record, setRecord] = useState<HistoricalObservationPayload | null>(
    null
  )
  const [error, setError] = useState<string | null>(null)

  // HistoricalObservationDialog is remounted per observation id (see the
  // `key` on its call site), so a fresh mount always starts from the initial
  // record/error state below and this effect only ever needs to populate it.
  useEffect(() => {
    if (!observationId) return
    let active = true
    fetchHistoricalObservation(observationId)
      .then((result) => {
        if (active) setRecord(result)
      })
      .catch((reason) => {
        if (active) setError(getApiErrorMessage(reason))
      })
    return () => {
      active = false
    }
  }, [observationId])

  const loading = observationId !== null && !record && !error

  const vehicle = record?.vehicle
    ? [
        record.vehicle.make,
        record.vehicle.model,
        record.vehicle.variant,
        record.vehicle.year,
      ]
        .filter(Boolean)
        .join(" ")
    : ""

  return (
    <Dialog
      open={observationId !== null}
      onOpenChange={(open) => !open && onClose()}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Historical source record</DialogTitle>
          <DialogDescription>
            Persisted historical claim observation used as comparison evidence.
          </DialogDescription>
        </DialogHeader>
        {loading ? (
          <p className="text-sm text-muted-foreground">
            Loading source record…
          </p>
        ) : error ? (
          <Alert variant="destructive">
            <AlertTitle>Source record unavailable</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : record ? (
          <div className="grid gap-4 text-sm">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-xs text-muted-foreground">Claim reference</p>
                <p className="font-medium">{record.claim_reference ?? "—"}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Invoice date</p>
                <p className="font-medium">{record.invoice_date ?? "—"}</p>
              </div>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Description</p>
              <p className="font-medium">{record.description ?? "—"}</p>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <p className="text-xs text-muted-foreground">
                  Line total (net)
                </p>
                <p className="font-medium tabular-nums">
                  {formatMoney(record.line_total_net ?? undefined)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Approved (net)</p>
                <p className="font-medium tabular-nums">
                  {formatMoney(record.approved_amount_net ?? undefined)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Settled (net)</p>
                <p className="font-medium tabular-nums">
                  {formatMoney(record.settled_amount_net ?? undefined)}
                </p>
              </div>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Vehicle</p>
              <p className="font-medium">{vehicle || "—"}</p>
            </div>
            {record.source_record_id ? (
              <p className="text-xs text-muted-foreground">
                Source record ID: {record.source_record_id}
              </p>
            ) : null}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

export function InlineMappingApproval({
  line,
  ontologyOptions,
  researchProposal,
  mappingSaving,
  onMappingDecision,
  researchSaving,
  onApproveResearch,
  onProposeNewItem,
}: {
  line: InvoiceLine
  ontologyOptions: OntologyBankItem[]
  researchProposal?: ResearchQueueItem | null
  mappingSaving: boolean
  onMappingDecision: (
    line: InvoiceLine,
    input: Omit<MappingDecisionInput, "actor">
  ) => Promise<void>
  researchSaving?: boolean
  onApproveResearch?: (item: ResearchQueueItem) => Promise<void>
  onProposeNewItem?: (
    line: InvoiceLine,
    values: ResearchFormValues
  ) => Promise<void>
}) {
  const [selection, setSelection] = useState<MappingDialogSelection | null>(
    null
  )
  const [researchOpen, setResearchOpen] = useState(false)

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg border bg-muted/30 p-3">
        <p className="text-xs font-medium text-muted-foreground">
          Suggested repair item match
        </p>
        <p className="mt-1 font-semibold">
          {line.ontologyName ??
            line.ontologyId ??
            researchProposal?.candidate ??
            "No candidate suggested"}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {researchProposal
            ? `New repair item proposal · ${researchProposal.status}`
            : line.mappingConfidence != null
              ? `${line.mappingConfidence}% confidence${line.mappingReviewStatus ? ` · ${line.mappingReviewStatus}` : ""}`
              : "Confidence unavailable"}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {line.ontologyId ? (
          <Button
            size="sm"
            disabled={mappingSaving}
            onClick={() => setSelection({ line, action: "approve" })}
          >
            <CheckIcon data-icon="inline-start" />
            Approve match
          </Button>
        ) : researchProposal?.researchItemId && onApproveResearch ? (
          <Button
            size="sm"
            disabled={Boolean(researchSaving)}
            onClick={() => void onApproveResearch(researchProposal)}
          >
            <CheckIcon data-icon="inline-start" />
            Approve new repair item
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="outline"
          disabled={mappingSaving}
          onClick={() => setSelection({ line, action: "change" })}
        >
          <PencilLineIcon data-icon="inline-start" />
          Change match…
        </Button>
        {onProposeNewItem ? (
          <Button
            size="sm"
            variant="ghost"
            disabled={Boolean(researchSaving)}
            onClick={() => setResearchOpen(true)}
          >
            <SearchIcon data-icon="inline-start" />
            Propose new item…
          </Button>
        ) : null}
      </div>
      {!line.ontologyId ? (
        <p className="text-xs text-muted-foreground">
          {researchProposal
            ? "This new repair item was staged automatically from the scanned line. Approve it to add it to the governed ontology bank and rerun the comparison."
            : "No candidate to approve yet. Use Change match to select an existing repair item or propose a new one."}
        </p>
      ) : null}
      {selection ? (
        <MappingDecisionDialog
          key={`${selection.line.id}-${selection.action}`}
          selection={selection}
          ontologyOptions={ontologyOptions}
          saving={mappingSaving}
          onOpenChange={(open) => {
            if (!open) setSelection(null)
          }}
          onSubmit={onMappingDecision}
        />
      ) : null}
      {onProposeNewItem ? (
        <ResearchDialog
          key={researchOpen ? `${line.id}-research-open` : "research-closed"}
          line={researchOpen ? line : null}
          open={researchOpen}
          onOpenChange={setResearchOpen}
          onSubmit={async (targetLine, values) => {
            await onProposeNewItem(targetLine, values)
            setResearchOpen(false)
          }}
          saving={Boolean(researchSaving)}
        />
      ) : null}
    </div>
  )
}

export function LineEvidenceSheet({
  line,
  onClose,
  p90ThresholdPct = 0,
  ontologyOptions,
  mappingSaving,
  onMappingDecision,
  researchSaving,
  onProposeNewItem,
}: {
  line: InvoiceLine | null
  onClose: () => void
  p90ThresholdPct?: number
  ontologyOptions?: OntologyBankItem[]
  mappingSaving?: boolean
  onMappingDecision?: (
    line: InvoiceLine,
    input: Omit<MappingDecisionInput, "actor">
  ) => Promise<void>
  researchSaving?: boolean
  onProposeNewItem?: (
    line: InvoiceLine,
    values: ResearchFormValues
  ) => Promise<void>
}) {
  const comparables = line?.comparables ?? []
  const p90 = line?.p90Benchmark
  // The operational status comes only from the server's comparisonStatus
  // (see backend price_decision.py) — never recomputed client-side here.
  const p90Challenged = Boolean(p90 && line?.comparisonStatus === "CHALLENGE")
  const [observationId, setObservationId] = useState<string | null>(null)
  return (
    <Sheet open={line !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{line?.description ?? "Line evidence"}</SheetTitle>
          <SheetDescription>
            Persisted evidence used for this line comparison.
          </SheetDescription>
        </SheetHeader>
        {line ? (
          <ScrollArea className="min-h-0 flex-1">
            <div className="flex flex-col gap-5 px-4 pb-6">
              {!isMappingApproved(line) && onMappingDecision ? (
                <div className="rounded-lg border border-warning/40 bg-warning/5 p-4">
                  <p className="text-sm font-medium">
                    Provisional finding: repair item match needs approval
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Approve, change, or propose a new repair item before this
                    evidence becomes actionable in Review findings.
                  </p>
                  <div className="mt-3">
                    <InlineMappingApproval
                      line={line}
                      ontologyOptions={ontologyOptions ?? []}
                      mappingSaving={Boolean(mappingSaving)}
                      onMappingDecision={onMappingDecision}
                      researchSaving={researchSaving}
                      onProposeNewItem={onProposeNewItem}
                    />
                  </div>
                </div>
              ) : null}
              {line.recommended !== undefined ? (
                <div className="rounded-lg border bg-primary/5 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-xs font-medium text-muted-foreground">
                        Operational price decision
                      </p>
                      <p className="mt-1 font-semibold">
                        50% in-house benchmark P90 + 30% historical claims P90 +
                        20% external reference price
                      </p>
                    </div>
                    <Badge
                      variant={line.challenge > 0 ? "destructive" : "outline"}
                    >
                      {line.challenge > 0
                        ? "Price challenge"
                        : "Within support"}
                    </Badge>
                  </div>
                  <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
                    <div>
                      <p className="text-xs text-muted-foreground">Billed</p>
                      <p className="font-semibold tabular-nums">
                        {formatMoney(line.currentTotal)}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Supported</p>
                      <p className="font-semibold tabular-nums">
                        {formatMoney(line.recommended)}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">
                        Difference
                      </p>
                      <p className="font-semibold tabular-nums">
                        {formatMoney(line.challenge)}
                      </p>
                    </div>
                  </div>
                  <p className="mt-3 text-xs leading-5 text-muted-foreground">
                    {line.evidenceRationale ?? line.rationale} The mapping model
                    may select a bounded repair item candidate; it never invents
                    a repair price.
                  </p>
                </div>
              ) : null}
              <CalculationBreakdown steps={line.calculation} />
              {p90 ? (
                <>
                  <div className="rounded-lg border bg-muted/30 p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="text-xs font-medium text-muted-foreground">
                          Historical claims P90 signal
                        </p>
                        <p className="mt-1 font-semibold">{p90.category}</p>
                      </div>
                      <Badge
                        variant={p90Challenged ? "destructive" : "outline"}
                      >
                        {p90Challenged ? "Challenge" : "Within threshold"}
                      </Badge>
                    </div>
                    <div className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                      <div>
                        <p className="text-xs text-muted-foreground">Current</p>
                        <p className="font-semibold tabular-nums">
                          {formatMoney(p90.currentPrice)}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">P90</p>
                        <p className="font-semibold tabular-nums">
                          {formatMoney(p90.p90)}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">
                          Difference
                        </p>
                        <p className="font-semibold tabular-nums">
                          {p90.difference > 0 ? "+" : ""}
                          {formatMoney(p90.difference)}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">
                          History used
                        </p>
                        <p className="font-semibold tabular-nums">
                          {p90.historicalCount}
                        </p>
                      </div>
                    </div>
                    <p className="mt-4 text-sm leading-6 text-muted-foreground">
                      {p90Challenged
                        ? `The current charge is ${p90.percentageDifference.toFixed(1)}% above P90 with a ${formatMoney(p90.difference)} difference, exceeding both the selected ${p90ThresholdPct}% threshold and the ${formatMoney(MINIMUM_CHALLENGE_AMOUNT)} minimum.`
                        : `A challenge requires both more than ${p90ThresholdPct}% above P90 and at least ${formatMoney(MINIMUM_CHALLENGE_AMOUNT)} difference.`}
                    </p>
                    <p className="mt-2 text-xs text-muted-foreground">
                      {p90.method}. Current invoice excluded: yes. When an
                      available governed source exists, it is weighted against
                      the full 50% in-house benchmark P90, 30% historical claims
                      P90 and 20% external reference price policy. Missing
                      sources are reweighted proportionally.
                    </p>
                  </div>

                  <div>
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <p className="font-medium">
                        Historical invoices used for P90
                      </p>
                      <Badge variant="outline">{p90.observations.length}</Badge>
                    </div>
                    <div className="overflow-x-auto rounded-lg border">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Invoice</TableHead>
                            <TableHead>Description</TableHead>
                            <TableHead className="text-right">Price</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {p90.observations.map((observation) => (
                            <TableRow key={observation.lineId}>
                              <TableCell>
                                <p className="font-medium">
                                  {observation.invoiceNumber}
                                </p>
                                <p className="text-xs text-muted-foreground">
                                  {observation.invoiceDate ??
                                    "Date unavailable"}
                                </p>
                              </TableCell>
                              <TableCell>{observation.description}</TableCell>
                              <TableCell className="text-right font-medium tabular-nums">
                                {formatMoney(observation.price)}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </div>
                  <Separator />
                </>
              ) : null}
              {!p90 ||
              comparables.length ||
              line.ontologyTotal !== undefined ||
              line.historicalMedian !== undefined ? (
                <>
                  <div className="grid grid-cols-3 gap-3 text-sm">
                    <div>
                      <p className="text-xs text-muted-foreground">Mapping</p>
                      <p className="font-medium tabular-nums">
                        {line.mappingConfidence ?? 0}%
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Evidence</p>
                      <p className="font-medium tabular-nums">
                        {line.evidenceConfidence ?? 0}%
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Challenge</p>
                      <p className="font-medium tabular-nums">
                        {line.challengeStrength ?? 0}/100
                      </p>
                    </div>
                  </div>
                  <Separator />
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <p className="text-xs text-muted-foreground">Ontology</p>
                      <p className="font-medium tabular-nums">
                        {formatMoney(line.ontologyTotal)}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {differenceLabel(line.differenceFromOntology)}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">
                        Historic median
                      </p>
                      <p className="font-medium tabular-nums">
                        {formatMoney(line.historicalMedian)}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {differenceLabel(line.differenceFromHistory)}
                      </p>
                      <p className="text-xs font-medium text-muted-foreground">
                        Context only — not part of the supported price
                      </p>
                    </div>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">
                      Evidence rationale
                    </p>
                    <p className="mt-1 text-sm">
                      {line.evidenceRationale ?? line.rationale}
                    </p>
                  </div>
                  <Separator />
                  <div>
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <p className="font-medium">Persisted comparables</p>
                      <Badge variant="outline">{comparables.length}</Badge>
                    </div>
                    {comparables.length ? (
                      <div className="flex flex-col gap-3">
                        {comparables.map((comparable) => {
                          const sourceReference =
                            typeof comparable.provenance.source_reference ===
                            "string"
                              ? comparable.provenance.source_reference
                              : null
                          const claimReference =
                            typeof comparable.provenance.claim_reference ===
                            "string"
                              ? comparable.provenance.claim_reference
                              : null
                          const invoiceNumber =
                            typeof comparable.comparabilityMetadata
                              ?.invoice_number === "string"
                              ? comparable.comparabilityMetadata.invoice_number
                              : null
                          const garageName =
                            typeof comparable.comparabilityMetadata
                              ?.garage_name === "string"
                              ? comparable.comparabilityMetadata.garage_name
                              : null
                          const vehicle = comparable.vehicle
                            ? [
                                comparable.vehicle.make,
                                comparable.vehicle.model,
                                comparable.vehicle.variant,
                                comparable.vehicle.year,
                              ]
                                .filter(Boolean)
                                .join(" ")
                            : ""
                          return (
                            <div
                              key={comparable.id}
                              className="rounded-lg border p-3 text-sm"
                            >
                              <div className="flex items-start justify-between gap-4">
                                <div className="min-w-0">
                                  <p className="font-medium">
                                    {comparable.description ??
                                      comparable.comparableClass}
                                  </p>
                                  <p className="text-xs break-words text-muted-foreground">
                                    {claimReference ||
                                      invoiceNumber ||
                                      (comparable.sourceType === "historical"
                                        ? "Historical claim"
                                        : "External reference source")}
                                    {" · "}
                                    {[invoiceNumber, garageName]
                                      .filter(Boolean)
                                      .join(" · ") || "Governed source record"}
                                  </p>
                                </div>
                                <div className="shrink-0 text-right">
                                  <p className="font-semibold tabular-nums">
                                    {formatMoney(
                                      comparable.priceNet ?? undefined
                                    )}
                                  </p>
                                  <p className="text-xs text-muted-foreground">
                                    weight {comparable.weight.toFixed(2)}
                                  </p>
                                </div>
                              </div>
                              <div className="mt-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
                                <p>
                                  {vehicle ||
                                    comparable.sourceType.replace("_", " ")}
                                </p>
                                <p className="sm:text-right">
                                  {comparable.observedDate ??
                                    "Date unavailable"}
                                </p>
                                <p className="sm:col-span-2">
                                  {comparable.eligibilityReason ??
                                    "Persisted as eligible"}
                                </p>
                              </div>
                              {sourceReference ? (
                                sourceReference.startsWith("http") ? (
                                  <a
                                    href={sourceReference}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary underline-offset-4 hover:underline"
                                  >
                                    Open source record
                                    <ExternalLinkIcon className="size-3" />
                                  </a>
                                ) : sourceReference.startsWith(
                                    HISTORICAL_OBSERVATION_PATH_PREFIX
                                  ) ? (
                                  <Button
                                    type="button"
                                    variant="link"
                                    size="sm"
                                    className="mt-2 h-auto p-0 text-xs font-medium"
                                    onClick={() =>
                                      setObservationId(
                                        sourceReference.slice(
                                          HISTORICAL_OBSERVATION_PATH_PREFIX.length
                                        )
                                      )
                                    }
                                  >
                                    View source record
                                    <ExternalLinkIcon className="size-3" />
                                  </Button>
                                ) : (
                                  <p className="mt-2 flex items-center gap-1 text-xs break-words text-muted-foreground">
                                    <FileTextIcon className="size-3 shrink-0" />
                                    {sourceReference}
                                  </p>
                                )
                              ) : null}
                            </div>
                          )
                        })}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        No persisted comparable observations for this line.
                      </p>
                    )}
                  </div>
                </>
              ) : null}
            </div>
          </ScrollArea>
        ) : null}
      </SheetContent>
      <HistoricalObservationDialog
        key={observationId ?? "closed"}
        observationId={observationId}
        onClose={() => setObservationId(null)}
      />
    </Sheet>
  )
}

export function PriceComparisonScreen({
  workspace,
  onInspect,
  onContinue,
}: {
  workspace: ClaimWorkspace
  onInspect: (line: InvoiceLine) => void
  onContinue: () => void
}) {
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState("all")
  const [challengedOnly, setChallengedOnly] = useState(true)
  const [evidenceLine, setEvidenceLine] = useState<InvoiceLine | null>(null)

  const rows = useMemo(
    () =>
      workspace.lines.filter((line) => {
        const matchesQuery = line.description
          .toLowerCase()
          .includes(query.toLowerCase())
        const matchesStatus =
          status === "all" || line.comparisonStatus.toLowerCase() === status
        const matchesChallenge =
          !challengedOnly || line.comparisonStatus === "CHALLENGE"
        return matchesQuery && matchesStatus && matchesChallenge
      }),
    [challengedOnly, query, status, workspace.lines]
  )

  return (
    <>
      <ScreenHeading
        title={`St Albans Car Clinic · Invoice ${workspace.invoice.number}`}
        description="Billed price, in-house benchmark P90, historical claims P90 and external reference price remain separate and traceable."
        action={
          <Button onClick={onContinue}>
            Review challenge
            <ArrowRightIcon data-icon="inline-end" />
          </Button>
        }
      />

      <ChallengeSummary workspace={workspace} />

      <Alert>
        <InfoIcon />
        <AlertTitle>Supported price policy · 50% / 30% / 20%</AlertTitle>
        <AlertDescription>
          The available in-house benchmark P90, historical claims P90 and
          external reference price are weighted 50%, 30% and 20%. Missing
          sources are proportionally reweighted. A line is challenged only when
          the positive variance passes the selected percentage threshold and the
          £5 minimum.
        </AlertDescription>
      </Alert>

      <DataCard
        title="Line comparison"
        description={`${rows.length} of ${workspace.lines.length} line items shown`}
      >
        <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
          <InputGroup className="min-w-0 flex-1">
            <InputGroupAddon>
              <SearchIcon />
            </InputGroupAddon>
            <InputGroupInput
              placeholder="Search line items"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label="Search line items"
            />
          </InputGroup>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger
              className="w-full lg:w-48"
              aria-label="Filter comparison status"
            >
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="challenge">Challenge</SelectItem>
                <SelectItem value="within">Within benchmark</SelectItem>
                <SelectItem value="below_gate">Below gate</SelectItem>
                <SelectItem value="missing">Missing evidence</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
          <label className="flex h-9 items-center gap-2 rounded-md border px-3 text-sm">
            <Checkbox
              checked={challengedOnly}
              onCheckedChange={(value) => setChallengedOnly(value === true)}
            />
            Challenged only
          </label>
        </div>

        <div className="overflow-x-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Invoice line</TableHead>
                <TableHead className="text-right">Current net</TableHead>
                <TableHead className="text-right">Ontology</TableHead>
                <TableHead className="text-right">Historic median</TableHead>
                <TableHead className="text-right">
                  Supported net price
                </TableHead>
                <TableHead className="text-right">Challenge</TableHead>
                <TableHead className="text-right">Strength</TableHead>
                <TableHead className="text-right">Status</TableHead>
                <TableHead className="w-10">
                  <span className="sr-only">Details</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((line) => (
                <TableRow
                  key={line.id}
                  data-state={
                    line.comparisonStatus === "CHALLENGE"
                      ? "selected"
                      : undefined
                  }
                >
                  <TableCell>
                    <div className="min-w-48">
                      <p className="font-medium">{line.description}</p>
                      <p className="text-xs text-muted-foreground">
                        {line.quantity} {line.unit} ·{" "}
                        {line.ontologyId ?? "No approved mapping"}
                      </p>
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {formatMoney(line.currentTotal)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    <p>{formatMoney(line.ontologyTotal)}</p>
                    <p className="text-xs text-muted-foreground">
                      {differenceLabel(line.differenceFromOntology)}
                    </p>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    <div>
                      <p>{formatMoney(line.historicalMedian)}</p>
                      <p className="text-xs text-muted-foreground">
                        {line.historicalCount} comps
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {differenceLabel(line.differenceFromHistory)}
                      </p>
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {formatMoney(line.recommended)}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    <span
                      className={
                        line.challenge > 0 ? "text-destructive" : undefined
                      }
                    >
                      {formatMoney(line.challenge)}
                    </span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {line.challengeStrength !== undefined
                      ? `${line.challengeStrength}/100`
                      : "—"}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end">
                      <StatusBadge
                        status={comparisonLabel(line.comparisonStatus)}
                      />
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => setEvidenceLine(line)}
                        aria-label={`View evidence for ${line.description}`}
                      >
                        <EyeIcon />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => onInspect(line)}
                        aria-label={`Inspect ${line.description}`}
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
      </DataCard>
      <LineEvidenceSheet
        line={evidenceLine}
        onClose={() => setEvidenceLine(null)}
      />
    </>
  )
}

const researchItems = [
  {
    id: "C0024",
    line: "Oil System Flush And Cleaner",
    ontology: "PART-0039 · Engine oil system flush treatment",
    candidate: "Engine flush treatment · 425 ml",
    price: "£6.80 net",
    source: "UK allow-listed supplier · captured 17 Jul 2026",
    confidence: "72%",
    ready: true,
  },
  {
    id: "C0026",
    line: "Fuel Injection Treatment",
    ontology: "PART-0040 · Fuel injection treatment",
    candidate: "Petrol injector cleaner treatment · 300 ml",
    price: "£8.25 net",
    source: "UK allow-listed supplier · captured 17 Jul 2026",
    confidence: "70%",
    ready: false,
  },
  {
    id: "C0034",
    line: "Front Wheel Alignment",
    ontology: "LAB-0007 · Front wheel alignment",
    candidate: "Front wheel alignment · passenger vehicle",
    price: "£45.00 net",
    source: "Regional workshop evidence · contract schedule pending",
    confidence: "68%",
    ready: false,
  },
  {
    id: "C0023",
    line: "Sundries - Grease/ Oil Etc",
    ontology: "PART-0041 · Sundries - grease / oils",
    candidate: "Workshop consumables allowance · per job",
    price: "£3.50 net",
    source: "Previous-invoice pattern · legitimacy review required",
    confidence: "61%",
    ready: false,
  },
]

export function LegacyMissingItemsScreen({
  approvedItems,
  researchedItems,
  onResearch,
  onApprove,
}: {
  approvedItems: Set<string>
  researchedItems: Set<string>
  onResearch: (id: string) => void
  onApprove: (id: string) => void
}) {
  return (
    <>
      <ScreenHeading
        title="Missing Items"
        description="Research is reviewer-initiated. Suggestions remain provisional until a handler approves them."
        action={<Badge variant="outline">auto_research: false</Badge>}
      />

      <Alert>
        <FlaskConicalIcon />
        <AlertTitle>
          Provisional evidence is excluded from challenge letters
        </AlertTitle>
        <AlertDescription>
          Pilot approval is one-step: one handler click creates the ontology
          item and immutable price observation. Maker-checker remains available
          through two_step_approval.
        </AlertDescription>
      </Alert>

      <DataCard
        title="Research queue"
        description="4 recognised items without an approved active price"
        action={<Badge variant="outline">two_step_approval: false</Badge>}
      >
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Invoice line</TableHead>
                <TableHead>Candidate</TableHead>
                <TableHead>Price</TableHead>
                <TableHead>Source</TableHead>
                <TableHead className="text-right">
                  Evidence confidence
                </TableHead>
                <TableHead className="text-right">State</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {researchItems.map((item) => {
                const researched = item.ready || researchedItems.has(item.id)
                const approved = approvedItems.has(item.id)
                return (
                  <TableRow key={item.id}>
                    <TableCell>
                      <div className="min-w-52">
                        <p className="font-medium">{item.line}</p>
                        <p className="text-xs text-muted-foreground">
                          {item.ontology}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell>
                      {researched ? item.candidate : "Research not run"}
                    </TableCell>
                    <TableCell className="font-medium tabular-nums">
                      {researched ? item.price : "—"}
                    </TableCell>
                    <TableCell className="max-w-xs text-muted-foreground">
                      {researched ? item.source : "Reviewer action required"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {researched ? item.confidence : "—"}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <StatusBadge
                          status={
                            approved
                              ? "APPROVED"
                              : researched
                                ? "PROVISIONAL"
                                : "RESEARCH REQUIRED"
                          }
                        />
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-2">
                        {!researched ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => onResearch(item.id)}
                          >
                            <SearchIcon data-icon="inline-start" />
                            Research
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            disabled={approved}
                            onClick={() => onApprove(item.id)}
                          >
                            <BadgeCheckIcon data-icon="inline-start" />
                            {approved ? "Approved" : "Approve"}
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      </DataCard>
    </>
  )
}

export interface ResearchFormValues {
  canonicalName: string
  itemType: string
  category: string
  unit: string
  priceNet: number
  sourceUri: string
  evidenceTitle: string
  rationale: string
  confidence: number
  dateChecked: string
  sourceAllowListVersion: string
}

function ResearchDialog({
  line,
  open,
  onOpenChange,
  onSubmit,
  saving,
}: {
  line: InvoiceLine | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (line: InvoiceLine, values: ResearchFormValues) => Promise<void>
  saving: boolean
}) {
  const [canonicalName, setCanonicalName] = useState(line?.description ?? "")
  const [itemType, setItemType] = useState(
    line?.kind === "Labour"
      ? "labour"
      : line?.kind === "Service"
        ? "service"
        : line?.kind === "Fee"
          ? "fee"
          : "part"
  )
  const [category, setCategory] = useState(line?.kind ?? "Unclassified")
  const [unit, setUnit] = useState(line?.unit || "each")
  const [priceNet, setPriceNet] = useState("")
  const [sourceUri, setSourceUri] = useState("")
  const [evidenceTitle, setEvidenceTitle] = useState("")
  const [rationale, setRationale] = useState("")
  const [confidence, setConfidence] = useState("0.70")

  function resetFromLine(nextLine: InvoiceLine | null) {
    setCanonicalName(nextLine?.description ?? "")
    setItemType(
      nextLine?.kind === "Labour"
        ? "labour"
        : nextLine?.kind === "Service"
          ? "service"
          : nextLine?.kind === "Fee"
            ? "fee"
            : "part"
    )
    setCategory(nextLine?.kind ?? "Unclassified")
    setUnit(nextLine?.unit || "each")
    setPriceNet("")
    setSourceUri("")
    setEvidenceTitle("")
    setRationale("")
    setConfidence("0.70")
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen) resetFromLine(line)
        onOpenChange(nextOpen)
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Research missing ontology item</DialogTitle>
          <DialogDescription>
            Enter evidence from an allow-listed source. Nothing reaches the
            ontology bank until a handler separately approves it.
          </DialogDescription>
        </DialogHeader>
        <form
          id="research-item-form"
          onSubmit={(event) => {
            event.preventDefault()
            if (!line) return
            void onSubmit(line, {
              canonicalName,
              itemType,
              category,
              unit,
              priceNet: Number(priceNet),
              sourceUri,
              evidenceTitle,
              rationale,
              confidence: Number(confidence),
              dateChecked: new Date().toISOString().slice(0, 10),
              sourceAllowListVersion: "pilot-manual-sources-v1",
            })
          }}
        >
          <FieldGroup>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="research-canonical-name">
                  Canonical item
                </FieldLabel>
                <Input
                  id="research-canonical-name"
                  value={canonicalName}
                  onChange={(event) => setCanonicalName(event.target.value)}
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="research-item-type">Item type</FieldLabel>
                <Select value={itemType} onValueChange={setItemType}>
                  <SelectTrigger id="research-item-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {[
                        "part",
                        "labour",
                        "service",
                        "fee",
                        "consumable",
                        "diagnostic",
                      ].map((value) => (
                        <SelectItem key={value} value={value}>
                          {value.replaceAll("_", " ")}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>
              <Field>
                <FieldLabel htmlFor="research-category">Category</FieldLabel>
                <Input
                  id="research-category"
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="research-unit">Unit</FieldLabel>
                <Input
                  id="research-unit"
                  value={unit}
                  onChange={(event) => setUnit(event.target.value)}
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="research-price">Net price</FieldLabel>
                <Input
                  id="research-price"
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={priceNet}
                  onChange={(event) => setPriceNet(event.target.value)}
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="research-confidence">
                  Evidence confidence
                </FieldLabel>
                <Input
                  id="research-confidence"
                  type="number"
                  min="0"
                  max="1"
                  step="0.01"
                  value={confidence}
                  onChange={(event) => setConfidence(event.target.value)}
                  required
                />
                <FieldDescription>Decimal from 0 to 1.</FieldDescription>
              </Field>
            </div>
            <Field>
              <FieldLabel htmlFor="research-source-uri">
                Allow-listed source URL
              </FieldLabel>
              <Input
                id="research-source-uri"
                type="url"
                value={sourceUri}
                onChange={(event) => setSourceUri(event.target.value)}
                placeholder="https://supplier.example.test/item"
                required
              />
              <FieldDescription>
                The API enforces the configured source allow-list and records a
                content hash.
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="research-evidence-title">
                Evidence title
              </FieldLabel>
              <Input
                id="research-evidence-title"
                value={evidenceTitle}
                onChange={(event) => setEvidenceTitle(event.target.value)}
                required
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="research-rationale">Rationale</FieldLabel>
              <Textarea
                id="research-rationale"
                value={rationale}
                onChange={(event) => setRationale(event.target.value)}
                required
              />
            </Field>
          </FieldGroup>
        </form>
        <DialogFooter showCloseButton>
          <Button type="submit" form="research-item-form" disabled={saving}>
            <SearchIcon data-icon="inline-start" />
            {saving ? "Saving evidence..." : "Save provisional evidence"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

const MANUAL_LINE_ACTOR = "pilot.handler"

const MANUAL_LINE_ITEM_KIND_OPTIONS = [
  { value: "part", label: "Part" },
  { value: "labour", label: "Labour" },
  { value: "paint", label: "Paint" },
  { value: "service", label: "Service" },
  { value: "disposal", label: "Disposal" },
  { value: "consumable", label: "Consumable" },
  { value: "unknown", label: "Other" },
] as const

interface ManualLineFormValues {
  description: string
  quantity: string
  unit: string
  lineTotalNet: string
  vatRate: string
  partNumber: string
  itemKind: string
}

const EMPTY_MANUAL_LINE_FORM: ManualLineFormValues = {
  description: "",
  quantity: "1",
  unit: "each",
  lineTotalNet: "",
  vatRate: "20",
  partNumber: "",
  itemKind: "part",
}

function ManualLineEntryDialog({
  document,
  invoice,
  open,
  onOpenChange,
  onSubmit,
  saving,
}: {
  document: UploadedDocument | null
  invoice: ClaimInvoiceSummary | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (
    invoice: ClaimInvoiceSummary,
    values: ManualLineFormValues
  ) => Promise<void>
  saving: boolean
}) {
  const [values, setValues] = useState<ManualLineFormValues>(
    EMPTY_MANUAL_LINE_FORM
  )

  const lineTotalValue = Number(values.lineTotalNet)
  const invalid =
    !values.description.trim() ||
    !Number.isFinite(lineTotalValue) ||
    lineTotalValue <= 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add line manually</DialogTitle>
          <DialogDescription>
            {document?.filename} · recorded as a handler-approved line so it
            flows into mapping and comparison on the next run.
          </DialogDescription>
        </DialogHeader>

        <FieldGroup>
          <Field data-invalid={!values.description.trim()}>
            <FieldLabel htmlFor="manual-line-description">
              Description
            </FieldLabel>
            <Input
              id="manual-line-description"
              value={values.description}
              onChange={(event) =>
                setValues((current) => ({
                  ...current,
                  description: event.target.value,
                }))
              }
              aria-invalid={!values.description.trim()}
              aria-required="true"
            />
          </Field>
          <FieldGroup className="grid sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="manual-line-quantity">Quantity</FieldLabel>
              <Input
                id="manual-line-quantity"
                type="number"
                min="0"
                step="0.01"
                value={values.quantity}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    quantity: event.target.value,
                  }))
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="manual-line-unit">Unit</FieldLabel>
              <Input
                id="manual-line-unit"
                value={values.unit}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    unit: event.target.value,
                  }))
                }
              />
            </Field>
          </FieldGroup>
          <FieldGroup className="grid sm:grid-cols-2">
            <Field
              data-invalid={
                !Number.isFinite(lineTotalValue) || lineTotalValue <= 0
              }
            >
              <FieldLabel htmlFor="manual-line-total">Net total</FieldLabel>
              <Input
                id="manual-line-total"
                type="number"
                min="0.01"
                step="0.01"
                value={values.lineTotalNet}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    lineTotalNet: event.target.value,
                  }))
                }
                aria-invalid={
                  !Number.isFinite(lineTotalValue) || lineTotalValue <= 0
                }
                aria-required="true"
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="manual-line-vat">VAT rate %</FieldLabel>
              <Input
                id="manual-line-vat"
                type="number"
                min="0"
                max="100"
                step="0.01"
                value={values.vatRate}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    vatRate: event.target.value,
                  }))
                }
              />
            </Field>
          </FieldGroup>
          <FieldGroup className="grid sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="manual-line-kind">Item kind</FieldLabel>
              <Select
                value={values.itemKind}
                onValueChange={(value) =>
                  setValues((current) => ({ ...current, itemKind: value }))
                }
              >
                <SelectTrigger id="manual-line-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MANUAL_LINE_ITEM_KIND_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor="manual-line-part-number">
                Part number
              </FieldLabel>
              <Input
                id="manual-line-part-number"
                value={values.partNumber}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    partNumber: event.target.value,
                  }))
                }
              />
            </Field>
          </FieldGroup>
        </FieldGroup>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button
            type="button"
            disabled={invalid || saving || !invoice}
            onClick={() => invoice && void onSubmit(invoice, values)}
          >
            {saving ? "Adding…" : "Add line"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ManualReviewDocumentsSection({
  caseReference,
  focusDocumentId,
  enabled = true,
}: {
  caseReference: string
  focusDocumentId?: string | null
  enabled?: boolean
}) {
  const [documents, setDocuments] = useState<UploadedDocument[]>([])
  const [pages, setPages] = useState<DocumentPageRecord[]>([])
  const [invoices, setInvoices] = useState<ClaimInvoiceSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [viewerPage, setViewerPage] = useState<DocumentPageRecord | null>(null)
  const [lineEntryDocument, setLineEntryDocument] =
    useState<UploadedDocument | null>(null)
  const [lineEntrySaving, setLineEntrySaving] = useState(false)
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({})

  const loadDocumentsAndInvoices = (isActive?: () => boolean) => {
    Promise.all([
      fetchCaseDocuments(caseReference),
      fetchDocumentPages(caseReference),
      fetchClaimInvoices(caseReference),
    ])
      .then(([documentRecords, pageRecords, invoiceRecords]) => {
        if (isActive && !isActive()) return
        setDocuments(documentRecords)
        setPages(pageRecords)
        setInvoices(invoiceRecords)
        setLoadError(null)
      })
      .catch((error: unknown) => {
        if (!isActive || isActive())
          setLoadError(documentApiErrorMessage(error))
      })
      .finally(() => {
        if (!isActive || isActive()) setLoading(false)
      })
  }

  useEffect(() => {
    let active = true
    loadDocumentsAndInvoices(() => active)
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseReference])

  useEffect(() => {
    if (!focusDocumentId) return
    const node = rowRefs.current[focusDocumentId]
    node?.scrollIntoView({ behavior: "smooth", block: "center" })
  }, [focusDocumentId, documents])

  const reviewDocuments = documents.filter(
    (document) => document.manual_review || document.status === "failed"
  )
  const invoiceByDocumentId = new Map(
    invoices
      .filter((invoice) => invoice.document_id)
      .map((invoice) => [invoice.document_id as string, invoice])
  )

  const handleManualLineSubmit = async (
    invoice: ClaimInvoiceSummary,
    values: ManualLineFormValues
  ) => {
    setLineEntrySaving(true)
    try {
      await addManualInvoiceLine(caseReference, invoice.id, {
        description: values.description.trim(),
        quantity: values.quantity ? Number(values.quantity) : undefined,
        unit: values.unit.trim() || undefined,
        lineTotalNet: Number(values.lineTotalNet),
        vatRate: values.vatRate ? Number(values.vatRate) : undefined,
        itemKind: values.itemKind,
        partNumber: values.partNumber.trim() || undefined,
        recordedBy: MANUAL_LINE_ACTOR,
      })
      toast.success("Line added", {
        description: `${values.description} was added to ${invoice.document_filename}.`,
      })
      setLineEntryDocument(null)
      loadDocumentsAndInvoices()
    } catch (error) {
      toast.error("Could not add line", {
        description: getApiErrorMessage(error),
      })
    } finally {
      setLineEntrySaving(false)
    }
  }

  return (
    <DataCard
      title="Documents needing manual review"
      description={`${reviewDocuments.length} document${reviewDocuments.length === 1 ? "" : "s"} could not be fully processed automatically`}
      action={
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={loading || reviewDocuments.length === 0}
          onClick={() =>
            downloadManualReviewCsv(
              caseReference,
              documents,
              pages,
              invoices
            )
          }
        >
          <DownloadIcon data-icon="inline-start" />
          Download staging CSV
        </Button>
      }
    >
      {loadError ? (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>Documents could not be loaded</AlertTitle>
          <AlertDescription>{loadError}</AlertDescription>
        </Alert>
      ) : loading ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          Loading documents…
        </p>
      ) : reviewDocuments.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No documents currently require manual review.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {reviewDocuments.map((document) => {
            const documentPages = pages.filter(
              (page) => page.document_id === document.id
            )
            return (
              <div
                key={document.id}
                ref={(node) => {
                  rowRefs.current[document.id] = node
                }}
                className={cn(
                  "rounded-lg border p-4",
                  focusDocumentId === document.id &&
                    "ring-2 ring-primary ring-offset-2 ring-offset-background"
                )}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1">
                      <p className="font-medium">{document.filename}</p>
                      <DocumentBriefingButton
                        filename={document.filename}
                        briefing={document.review_briefing}
                      />
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {document.page_count ?? 0} page
                      {document.page_count === 1 ? "" : "s"} ·{" "}
                      {document.status.replaceAll("_", " ")}
                    </p>
                  </div>
                  <StatusBadge
                    status={
                      document.status === "failed" ? "FAILED" : "MANUAL REVIEW"
                    }
                  />
                </div>
                <div className="mt-3 flex items-start gap-2 rounded-md bg-muted/30 p-3 text-sm">
                  <InfoIcon
                    className="mt-0.5 size-4 shrink-0 text-muted-foreground"
                    aria-hidden
                  />
                  <p className="text-muted-foreground">
                    {document.manual_review_reason ??
                      "No further detail was returned for this document. Open the info icon above for the AI briefing, if one is available."}
                  </p>
                </div>
                {documentPages.length ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {documentPages.map((page) => (
                      <button
                        key={page.id}
                        type="button"
                        onClick={() => setViewerPage(page)}
                        className="overflow-hidden rounded-md border transition hover:ring-2 hover:ring-primary"
                        aria-label={`Enlarge page ${page.page_number} of ${document.filename}`}
                      >
                        <img
                          src={documentImageUrl(page.image_url)}
                          alt={`Page ${page.page_number} thumbnail of ${document.filename}`}
                          loading="lazy"
                          className="h-20 w-16 object-cover"
                        />
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="mt-3 text-xs text-muted-foreground">
                    No page images are available for this document yet.
                  </p>
                )}
                <div className="mt-3 flex items-center justify-between gap-2 border-t pt-3">
                  <p className="text-xs text-muted-foreground">
                    {invoiceByDocumentId.has(document.id)
                      ? "Add billable lines by hand; they flow into mapping and comparison on the next run."
                      : "Awaiting an invoice record for this document before lines can be added."}
                  </p>
                  {invoiceByDocumentId.has(document.id) ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={!enabled}
                      onClick={() => setLineEntryDocument(document)}
                    >
                      <PlusIcon data-icon="inline-start" />
                      Add line manually
                    </Button>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>
      )}
      <ManualLineEntryDialog
        key={lineEntryDocument?.id ?? "closed-manual-line-dialog"}
        document={lineEntryDocument}
        invoice={
          lineEntryDocument
            ? (invoiceByDocumentId.get(lineEntryDocument.id) ?? null)
            : null
        }
        open={lineEntryDocument !== null}
        onOpenChange={(open) => !open && setLineEntryDocument(null)}
        onSubmit={handleManualLineSubmit}
        saving={lineEntrySaving}
      />
      <Dialog
        open={viewerPage !== null}
        onOpenChange={(open) => !open && setViewerPage(null)}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {viewerPage ? `Page ${viewerPage.page_number}` : "Page image"}
            </DialogTitle>
            <DialogDescription>
              {viewerPage?.document_filename ?? "Document page image"}
            </DialogDescription>
          </DialogHeader>
          {viewerPage ? (
            <img
              src={documentImageUrl(viewerPage.image_url)}
              alt={`Page ${viewerPage.page_number} of ${viewerPage.document_filename}`}
              className="w-full rounded-md border"
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </DataCard>
  )
}

export function MissingItemsScreen({
  workspace,
  enabled,
  saving,
  onResearch,
  onApprove,
  focusDocumentId,
}: {
  workspace: ClaimWorkspace
  enabled: boolean
  saving: boolean
  onResearch: (line: InvoiceLine, values: ResearchFormValues) => Promise<void>
  onApprove: (item: ResearchQueueItem) => Promise<void>
  focusDocumentId?: string | null
}) {
  const [researchLine, setResearchLine] = useState<InvoiceLine | null>(null)
  const missingLines = workspace.lines.filter(
    (line) => line.mappingStatus === "NO_MATCH"
  )
  const researchByLine = new Map(
    (workspace.researchItems ?? []).map((item) => [item.lineId, item])
  )

  return (
    <>
      <ScreenHeading
        title="Manual review"
        description="Documents that need a closer look, plus new repair item proposals awaiting handler approval."
        action={<Badge variant="outline">auto_research: false</Badge>}
      />
      <ManualReviewDocumentsSection
        caseReference={workspace.claim.id}
        focusDocumentId={focusDocumentId}
        enabled={enabled}
      />
      <Alert>
        <FlaskConicalIcon />
        <AlertTitle>Provisional evidence stays out of letters</AlertTitle>
        <AlertDescription>
          One handler approval creates the active ontology item for the pilot.
          The source, capture date, confidence and immutable evidence lineage
          remain attached.
        </AlertDescription>
      </Alert>
      <DataCard
        title="New repair item proposals"
        description={`${missingLines.length} invoice line${missingLines.length === 1 ? "" : "s"} without an approved mapping`}
        action={<Badge variant="outline">two_step_approval: false</Badge>}
      >
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Invoice line</TableHead>
                <TableHead>Candidate</TableHead>
                <TableHead>Net price</TableHead>
                <TableHead>Source</TableHead>
                <TableHead className="text-right">Confidence</TableHead>
                <TableHead className="text-right">State</TableHead>
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {missingLines.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={7}
                    className="py-8 text-center text-muted-foreground"
                  >
                    No missing ontology items in this claim.
                  </TableCell>
                </TableRow>
              ) : null}
              {missingLines.map((line) => {
                const item = researchByLine.get(line.id)
                const approved = item?.status === "APPROVED"
                return (
                  <TableRow key={line.id}>
                    <TableCell>
                      <p className="font-medium">{line.description}</p>
                      <p className="text-xs text-muted-foreground">
                        {line.partNumber || line.kind}
                      </p>
                    </TableCell>
                    <TableCell>
                      {item?.candidate || "Research required"}
                    </TableCell>
                    <TableCell className="font-medium tabular-nums">
                      {item?.priceNet == null
                        ? "—"
                        : formatMoney(item.priceNet)}
                    </TableCell>
                    <TableCell className="max-w-xs truncate text-muted-foreground">
                      {item?.sourceUrls[0] || "Reviewer action required"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {item?.confidence == null ? "—" : `${item.confidence}%`}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <StatusBadge
                          status={item?.status || "RESEARCH REQUIRED"}
                        />
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        {!item ? (
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={!enabled || saving}
                            onClick={() => setResearchLine(line)}
                          >
                            <SearchIcon data-icon="inline-start" />
                            Research
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            disabled={
                              !enabled ||
                              saving ||
                              approved ||
                              !item.researchItemId
                            }
                            onClick={() => void onApprove(item)}
                          >
                            <BadgeCheckIcon data-icon="inline-start" />
                            {approved ? "Approved" : "Approve"}
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      </DataCard>
      <ResearchDialog
        key={researchLine?.id ?? "closed-research-dialog"}
        line={researchLine}
        open={researchLine !== null}
        onOpenChange={(open) => !open && setResearchLine(null)}
        onSubmit={async (line, values) => {
          await onResearch(line, values)
          setResearchLine(null)
        }}
        saving={saving}
      />
    </>
  )
}

type ChallengeDecisionMode = "approve" | "reject" | "edit"

export function ChallengeDecisionDialog({
  line,
  mode,
  saving,
  onClose,
  onSubmit,
}: {
  line: InvoiceLine | null
  mode: ChallengeDecisionMode | null
  saving: boolean
  onClose: () => void
  onSubmit: (values: {
    approved: boolean
    rationale: string
    challengePriceNet?: number
  }) => Promise<void>
}) {
  const [rationale, setRationale] = useState("")
  const [challengePrice, setChallengePrice] = useState(
    line?.recommended?.toFixed(2) ?? ""
  )
  const editing = mode === "edit"
  const rejecting = mode === "reject"
  const maximumChallengePrice = Math.max(
    0.01,
    Number(((line?.currentTotal ?? 0) - 0.01).toFixed(2))
  )
  const challengePriceNumber = Number(challengePrice)
  const invalidChallengePrice =
    editing &&
    (!Number.isFinite(challengePriceNumber) ||
      challengePriceNumber <= 0 ||
      challengePriceNumber >= (line?.currentTotal ?? 0))

  return (
    <Dialog
      open={line !== null && mode !== null}
      onOpenChange={(open) => !open && onClose()}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {editing
              ? "Edit supported net price"
              : rejecting
                ? "Reject line challenge"
                : "Accept line challenge"}
          </DialogTitle>
          <DialogDescription>
            {line?.description}. This human decision and rationale are written
            to the append-only audit trail.
          </DialogDescription>
        </DialogHeader>
        <form
          id="challenge-decision-form"
          onSubmit={(event) => {
            event.preventDefault()
            if (invalidChallengePrice) return
            void onSubmit({
              approved: !rejecting,
              rationale,
              challengePriceNet: rejecting
                ? undefined
                : editing
                  ? Number(challengePrice)
                  : line?.recommended,
            })
          }}
        >
          <FieldGroup>
            {editing ? (
              <Field>
                <FieldLabel htmlFor="challenge-price-net">
                  Supported net line price
                </FieldLabel>
                <Input
                  id="challenge-price-net"
                  type="number"
                  min="0.01"
                  max={maximumChallengePrice}
                  step="0.01"
                  value={challengePrice}
                  onChange={(event) => setChallengePrice(event.target.value)}
                  required
                />
                <FieldDescription>
                  Current net {formatMoney(line?.currentTotal)} · calculated
                  recommendation {formatMoney(line?.recommended)}. Enter a
                  positive amount below the current net total; reject the
                  challenge instead if no reduction is needed.
                </FieldDescription>
                {invalidChallengePrice ? (
                  <p className="text-xs font-medium text-destructive">
                    Supported net price must be more than £0.00 and less than{" "}
                    {formatMoney(line?.currentTotal)}.
                  </p>
                ) : null}
              </Field>
            ) : null}
            <Field>
              <FieldLabel htmlFor="challenge-decision-rationale">
                Handler rationale
              </FieldLabel>
              <Textarea
                id="challenge-decision-rationale"
                value={rationale}
                onChange={(event) => setRationale(event.target.value)}
                placeholder={
                  rejecting
                    ? "Why should this variance not be challenged?"
                    : "Why is this evidence and supported net price appropriate?"
                }
                required
              />
            </Field>
          </FieldGroup>
        </form>
        <DialogFooter showCloseButton>
          <Button
            type="submit"
            form="challenge-decision-form"
            variant={rejecting ? "destructive" : "default"}
            disabled={saving || invalidChallengePrice}
          >
            {rejecting ? (
              <XCircleIcon data-icon="inline-start" />
            ) : editing ? (
              <PencilLineIcon data-icon="inline-start" />
            ) : (
              <CheckCheckIcon data-icon="inline-start" />
            )}
            {saving
              ? "Saving decision..."
              : editing
                ? "Save edited price"
                : rejecting
                  ? "Reject challenge"
                  : "Accept challenge"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function ChallengeReviewScreen({
  workspace,
  canIssue,
  comparisonReady,
  finalised,
  processing,
  enabled,
  onFinalise,
  onDecision,
  onSettlement,
  onDownload,
}: {
  workspace: ClaimWorkspace
  canIssue: boolean
  comparisonReady: boolean
  finalised: boolean
  processing: boolean
  enabled: boolean
  onFinalise: () => void
  onDecision: (
    line: InvoiceLine,
    decision: {
      approved: boolean
      rationale: string
      challengePriceNet?: number
    }
  ) => Promise<void>
  onSettlement: () => void
  onDownload: (format: "docx" | "pdf") => void
}) {
  const [decisionLine, setDecisionLine] = useState<InvoiceLine | null>(null)
  const [decisionMode, setDecisionMode] =
    useState<ChallengeDecisionMode | null>(null)
  const challenged = workspace.lines.filter((line) => line.challenge > 0)
  const unresolved = challenged.filter(
    (line) =>
      !["approved", "rejected"].includes(line.challengeStatus ?? "review")
  )
  const canFinalise =
    enabled && canIssue && comparisonReady && unresolved.length === 0

  return (
    <>
      <ScreenHeading
        title="Challenge Review"
        description="Approve the net challenge and its negotiation evidence before generating an output."
        action={
          <>
            <Button
              variant="outline"
              onClick={onSettlement}
              disabled={processing}
            >
              <BanknoteIcon data-icon="inline-start" />
              Capture settlement
            </Button>
            <Button
              onClick={onFinalise}
              disabled={finalised || processing || !canFinalise}
            >
              <CheckCheckIcon data-icon="inline-start" />
              {finalised
                ? "Case finalised"
                : processing
                  ? "Finalising..."
                  : canFinalise
                    ? "Finalise reviewed challenge"
                    : unresolved.length > 0
                      ? `${unresolved.length} decision${unresolved.length === 1 ? "" : "s"} remaining`
                      : "Issuance gated"}
            </Button>
          </>
        }
      />

      <ChallengeSummary workspace={workspace} />

      {!canIssue && !finalised ? (
        <Alert>
          <InfoIcon />
          <AlertTitle>Draft analysis only</AlertTitle>
          <AlertDescription>
            Review can continue for {workspace.liability.status}. Challenge
            issuance and negotiation letters require a human-confirmed ADMITTED
            or SPLIT LIABILITY decision.
          </AlertDescription>
        </Alert>
      ) : null}

      {canIssue && !comparisonReady && !finalised ? (
        <Alert>
          <InfoIcon />
          <AlertTitle>Recomparison required</AlertTitle>
          <AlertDescription>
            A corrected invoice returned this case to extraction review.
            Reprocess the invoice and rerun comparison before deciding challenge
            lines or finalising.
          </AlertDescription>
        </Alert>
      ) : null}

      <DataCard
        title="Challenged lines"
        description="Positive variances only; cheaper lines do not offset them."
      >
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Invoice line</TableHead>
                <TableHead className="text-right">Current net</TableHead>
                <TableHead className="text-right">
                  Supported net price
                </TableHead>
                <TableHead className="text-right">Challenge</TableHead>
                <TableHead className="text-right">Mapping confidence</TableHead>
                <TableHead className="text-right">
                  Evidence confidence
                </TableHead>
                <TableHead className="text-right">Strength</TableHead>
                <TableHead className="text-right">Decision</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {challenged.map((line) => (
                <TableRow key={line.id}>
                  <TableCell>
                    <p className="font-medium">{line.description}</p>
                    <p className="text-xs text-muted-foreground">
                      {line.ontologyId}
                    </p>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(line.currentTotal)}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {formatMoney(line.recommended)}
                  </TableCell>
                  <TableCell className="text-right font-medium text-destructive tabular-nums">
                    {formatMoney(line.challenge)}
                  </TableCell>
                  <TableCell className="text-right">
                    <ConfidenceCell value={line.mappingConfidence} />
                  </TableCell>
                  <TableCell className="text-right">
                    <ConfidenceCell value={line.evidenceConfidence} />
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {line.challengeStrength}/100
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end">
                      <StatusBadge
                        status={(
                          line.challengeStatus ?? "review"
                        ).toUpperCase()}
                      />
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!enabled || finalised || processing}
                        onClick={() => {
                          setDecisionLine(line)
                          setDecisionMode("approve")
                        }}
                      >
                        Accept
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!enabled || finalised || processing}
                        onClick={() => {
                          setDecisionLine(line)
                          setDecisionMode("edit")
                        }}
                      >
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={!enabled || finalised || processing}
                        onClick={() => {
                          setDecisionLine(line)
                          setDecisionMode("reject")
                        }}
                      >
                        Reject
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </DataCard>

      <div className="grid gap-6 lg:grid-cols-2">
        <DataCard
          title="Letter arithmetic"
          description="Net figures throughout; VAT impact is separate."
        >
          <div className="flex flex-col gap-3 text-sm">
            {[
              [
                "Original net invoice incl. MOT",
                formatMoney(workspace.invoice.netIncludingMot),
              ],
              [
                "Proposed payable net",
                formatMoney(workspace.summary.challengePrice),
              ],
              [
                "Net challenge amount",
                formatMoney(workspace.summary.challengeAmount),
              ],
              ["VAT impact", formatMoney(workspace.summary.vatImpact)],
              ["Gross cash effect", formatMoney(workspace.summary.grossEffect)],
              ["MOT treatment", "£54.85 outside VAT"],
            ].map(([label, value]) => (
              <div
                key={label}
                className="flex items-center justify-between gap-4"
              >
                <span className="text-muted-foreground">{label}</span>
                <span className="font-medium tabular-nums">{value}</span>
              </div>
            ))}
          </div>
        </DataCard>
        <Card>
          <CardHeader>
            <CardTitle>Negotiation evidence</CardTitle>
            <CardDescription>
              Included in the reviewed output package.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm">
            {[
              "Invoice line and corrected extraction",
              "Ontology item and active version",
              "Previous invoice comparables and date range",
              "70/30 policy calculation and £5/5% gates",
              "Mapping, evidence and challenge-strength scores",
              "Handler approval and immutable audit record",
            ].map((item) => (
              <div key={item} className="flex items-start gap-2">
                <CheckCheckIcon
                  className="mt-0.5 size-4 shrink-0 text-success"
                  aria-hidden
                />
                <span>{item}</span>
              </div>
            ))}
          </CardContent>
          <CardFooter>
            {finalised ? (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => onDownload("docx")}>
                  <DownloadIcon data-icon="inline-start" />
                  Download DOCX
                </Button>
                <Button variant="outline" onClick={() => onDownload("pdf")}>
                  <FileTextIcon data-icon="inline-start" />
                  Download PDF
                </Button>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                DOCX and PDF become available after every positive line is
                decided and the case is finalised.
              </p>
            )}
          </CardFooter>
        </Card>
      </div>
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

export function LegacyOntologyBankScreen({
  approvedItems,
}: {
  approvedItems: Set<string>
}) {
  const activeVersion = approvedItems.size > 0 ? "v1.1" : "v1.0"
  const coreItems = [
    [
      "PART-0003",
      "Air filter (engine)",
      "Part",
      "£12.42 / each",
      "9",
      "ACTIVE",
    ],
    [
      "PART-0001",
      "Engine oil (per litre)",
      "Part",
      "£9.75 / litre",
      "13",
      "ACTIVE",
    ],
    [
      "LAB-0002",
      "Full / main service labour",
      "Labour",
      "£138.00 / job",
      "5",
      "ACTIVE",
    ],
    [
      "LAB-0004",
      "Fit front brake discs & pads",
      "Labour",
      "£60.00 / job",
      "1",
      "ACTIVE",
    ],
  ]
  const newlyApproved = researchItems
    .filter((item) => approvedItems.has(item.id))
    .map((item) => [
      item.ontology.split(" · ")[0],
      item.candidate,
      "Provisional item",
      item.price,
      "1",
      "ACTIVE",
    ])
  const items = [...newlyApproved, ...coreItems]
  const versions =
    approvedItems.size > 0
      ? [
          [
            "v1.1",
            `Added ${approvedItems.size} handler-approved item`,
            `${72 + approvedItems.size} items`,
            "17 Jul 2026",
            "ACTIVE",
          ],
          [
            "v1.0",
            "Initial generated ontology",
            "72 items",
            "17 Jul 2026",
            "SUPERSEDED",
          ],
          ontologyVersions[1],
        ]
      : ontologyVersions

  return (
    <>
      <ScreenHeading
        title="Ontology Bank"
        description="Immutable versions connect current invoice lines, approved price evidence and previous invoices."
        action={<Badge variant="success">{activeVersion} ACTIVE</Badge>}
      />

      <Tabs defaultValue="items">
        <TabsList>
          <TabsTrigger value="items">Items</TabsTrigger>
          <TabsTrigger value="versions">Versions</TabsTrigger>
          <TabsTrigger value="observations">Price observations</TabsTrigger>
        </TabsList>

        <TabsContent value="items" className="mt-4">
          <DataCard
            title="Canonical items"
            description="72 active items · selected pilot rows shown"
          >
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>Canonical item</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Reference price</TableHead>
                    <TableHead className="text-right">Observations</TableHead>
                    <TableHead className="text-right">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map(
                    ([id, name, type, price, observations, status]) => (
                      <TableRow key={id}>
                        <TableCell className="font-mono text-xs">
                          {id}
                        </TableCell>
                        <TableCell className="font-medium">{name}</TableCell>
                        <TableCell>{type}</TableCell>
                        <TableCell className="tabular-nums">{price}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {observations}
                        </TableCell>
                        <TableCell>
                          <div className="flex justify-end">
                            <StatusBadge status={status} />
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  )}
                </TableBody>
              </Table>
            </div>
          </DataCard>
        </TabsContent>

        <TabsContent value="versions" className="mt-4">
          <DataCard
            title="Version history"
            description="New approvals publish a new immutable version."
          >
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Version</TableHead>
                    <TableHead>Change</TableHead>
                    <TableHead>Size</TableHead>
                    <TableHead>Published</TableHead>
                    <TableHead className="text-right">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {versions.map(
                    ([version, change, size, published, status]) => (
                      <TableRow key={version}>
                        <TableCell className="font-medium">{version}</TableCell>
                        <TableCell>{change}</TableCell>
                        <TableCell>{size}</TableCell>
                        <TableCell>{published}</TableCell>
                        <TableCell>
                          <div className="flex justify-end">
                            <StatusBadge status={status} />
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  )}
                </TableBody>
              </Table>
            </div>
          </DataCard>
        </TabsContent>

        <TabsContent value="observations" className="mt-4">
          <DataCard
            title="Price observations"
            description="Sources and capture dates remain attached to every price."
          >
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Ontology item</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>Basis</TableHead>
                    <TableHead className="text-right">Net price</TableHead>
                    <TableHead className="text-right">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[
                    [
                      "PART-0003",
                      "Previous repair invoices",
                      "02 Aug 2024",
                      "Median · 9 observations",
                      "£12.42",
                      "APPROVED",
                    ],
                    [
                      "PART-0001",
                      "Previous repair invoices",
                      "02 Aug 2024",
                      "Median · 13 observations",
                      "£9.75",
                      "APPROVED",
                    ],
                    [
                      "LAB-0002",
                      "Previous repair invoices",
                      "31 Oct 2023",
                      "Median · 5 observations",
                      "£138.00",
                      "APPROVED",
                    ],
                  ].map(([item, source, date, basis, price, status]) => (
                    <TableRow key={item}>
                      <TableCell className="font-mono text-xs">
                        {item}
                      </TableCell>
                      <TableCell>{source}</TableCell>
                      <TableCell>{date}</TableCell>
                      <TableCell>{basis}</TableCell>
                      <TableCell className="text-right font-medium tabular-nums">
                        {price}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end">
                          <StatusBadge status={status} />
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </DataCard>
        </TabsContent>
      </Tabs>
    </>
  )
}

export function LegacyAuditReportsScreen({
  onExport,
}: {
  onExport: (format: "json" | "xlsx" | "sqlite") => void
}) {
  return (
    <>
      <ScreenHeading
        title="Audit & Reports"
        description="Reproducible outputs are stamped with source hashes, policy v1.4 and ontology v1.0."
        action={<Badge variant="outline">CG-2026-0048</Badge>}
      />

      <div className="grid gap-6 lg:grid-cols-3">
        {[
          [
            "JSON evidence pack",
            "Machine-readable claim, extraction and challenge record",
            FileJson2Icon,
            "json",
          ],
          [
            "Excel review workbook",
            "Line-level mappings, comparables and calculation checks",
            FileSpreadsheetIcon,
            "xlsx",
          ],
          [
            "SQLite case database",
            "Portable immutable pilot record and audit trail",
            DatabaseIcon,
            "sqlite",
          ],
        ].map(([title, description, Icon, format]) => {
          const ExportIcon = Icon as typeof FileJson2Icon
          return (
            <Card key={String(format)}>
              <CardHeader>
                <span className="flex size-9 items-center justify-center rounded-md bg-muted">
                  <ExportIcon className="size-5" aria-hidden />
                </span>
                <CardTitle>{String(title)}</CardTitle>
                <CardDescription>{String(description)}</CardDescription>
              </CardHeader>
              <CardFooter>
                <Button
                  variant="outline"
                  onClick={() => onExport(format as "json" | "xlsx" | "sqlite")}
                >
                  <DownloadIcon data-icon="inline-start" />
                  Download {String(format).toUpperCase()}
                </Button>
              </CardFooter>
            </Card>
          )
        })}
      </div>

      <DataCard
        title="Audit history"
        description="Human and automated events remain append-only."
      >
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Event</TableHead>
                <TableHead>Value</TableHead>
                <TableHead>Record hash</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {auditEvents.map(([time, actor, event, value, hash]) => (
                <TableRow key={`${time}-${event}`}>
                  <TableCell>{time}</TableCell>
                  <TableCell>{actor}</TableCell>
                  <TableCell className="font-medium">{event}</TableCell>
                  <TableCell>{value}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {hash}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </DataCard>

      <Alert>
        <ShieldCheckIcon />
        <AlertTitle>Audit-ready by construction</AlertTitle>
        <AlertDescription>
          Raw extraction, model suggestion, handler correction, policy
          calculation and issued-report version are retained as separate
          records.
        </AlertDescription>
      </Alert>
    </>
  )
}

function externalPriceMethod(
  item: OntologyBankItem,
  observations: PriceObservationRecord[]
) {
  const prices = observations
    .filter(
      (observation) => observation.approvalStatus.toLowerCase() === "approved"
    )
    .map((observation) => observation.priceNet)
    .sort((left, right) => left - right)
  if (!prices.length || item.referencePriceNet == null) {
    if (observations.length && item.referencePriceNet != null) {
      return `Governed library value; ${observations.length} observation${observations.length === 1 ? " remains" : "s remain"} provisional and excluded until approved.`
    }
    return "No approved external observations are available."
  }
  const middle = Math.floor(prices.length / 2)
  const median =
    prices.length % 2
      ? prices[middle]
      : (prices[middle - 1] + prices[middle]) / 2
  const mean = prices.reduce((total, price) => total + price, 0) / prices.length
  if (Math.abs(item.referencePriceNet - median) < 0.01) {
    return `Median of ${prices.length} approved external observation${prices.length === 1 ? "" : "s"}.`
  }
  if (Math.abs(item.referencePriceNet - mean) < 0.01) {
    return `Mean of ${prices.length} approved external observation${prices.length === 1 ? "" : "s"}.`
  }
  return "Governed approved library price; individual observations are shown below."
}

export function OntologyBankScreen({
  workspace,
}: {
  workspace: ClaimWorkspace
}) {
  const bank = workspace.ontologyBank ?? {
    items: [],
    versions: [],
    priceObservations: [],
  }
  const activeVersion = workspace.versions?.ontology ?? "unversioned"
  const [selectedItem, setSelectedItem] = useState<OntologyBankItem | null>(
    null
  )
  const selectedObservations = selectedItem
    ? bank.priceObservations.filter(
        (observation) => observation.ontologyItemId === selectedItem.id
      )
    : []

  return (
    <>
      <ScreenHeading
        title="External Price Library"
        description="Approved external prices with source traceability. Provisional observations do not affect challenge calculations."
        action={<Badge variant="success">{activeVersion} ACTIVE</Badge>}
      />
      <Tabs defaultValue="items">
        <TabsList>
          <TabsTrigger value="items">Items</TabsTrigger>
          <TabsTrigger value="versions">Versions</TabsTrigger>
          <TabsTrigger value="observations">Price observations</TabsTrigger>
        </TabsList>
        <TabsContent value="items" className="mt-4">
          <DataCard
            title="Canonical items"
            description={`${bank.items.length} persisted item${bank.items.length === 1 ? "" : "s"}`}
          >
            <div className="max-h-[34rem] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>Canonical item</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>External price</TableHead>
                    <TableHead className="text-right">Observations</TableHead>
                    <TableHead className="text-right">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {bank.items.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={6}
                        className="py-8 text-center text-muted-foreground"
                      >
                        Connect the FastAPI service to inspect the ontology
                        bank.
                      </TableCell>
                    </TableRow>
                  ) : null}
                  {bank.items.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="font-mono text-xs">
                        {item.code}
                      </TableCell>
                      <TableCell>
                        <p className="font-medium">{item.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {item.category} ·{" "}
                          {item.createdInVersion || "unversioned"}
                        </p>
                      </TableCell>
                      <TableCell>{item.itemType}</TableCell>
                      <TableCell className="tabular-nums">
                        {item.referencePriceNet == null
                          ? "—"
                          : `${formatMoney(item.referencePriceNet)} / ${item.unit}`}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => setSelectedItem(item)}
                        >
                          <EyeIcon data-icon="inline-start" />
                          {item.observationCount} source
                          {item.observationCount === 1 ? "" : "s"}
                        </Button>
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end">
                          <StatusBadge status={item.approvalStatus} />
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </DataCard>
        </TabsContent>
        <TabsContent value="versions" className="mt-4">
          <DataCard
            title="Version history"
            description="Every research approval publishes a new immutable ontology version."
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Version</TableHead>
                  <TableHead>Sequence</TableHead>
                  <TableHead>Published</TableHead>
                  <TableHead className="text-right">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {bank.versions.map((version) => (
                  <TableRow key={`${version.type}-${version.version}`}>
                    <TableCell className="font-medium">
                      {version.version}
                    </TableCell>
                    <TableCell>{version.sequence ?? "—"}</TableCell>
                    <TableCell>
                      {version.published_at
                        ? new Date(version.published_at).toLocaleString("en-GB")
                        : "—"}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <StatusBadge status={version.status} />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </DataCard>
        </TabsContent>
        <TabsContent value="observations" className="mt-4">
          <DataCard
            title="Price observations"
            description={`${bank.priceObservations.length} latest persisted observations shown`}
          >
            <div className="max-h-[34rem] overflow-auto">
              <Table className="min-w-[72rem]">
                <TableHeader>
                  <TableRow>
                    <TableHead>Ontology item</TableHead>
                    <TableHead>Provider</TableHead>
                    <TableHead>Source evidence</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>Scope / VAT</TableHead>
                    <TableHead className="text-right">
                      Published price
                    </TableHead>
                    <TableHead className="text-right">Net price</TableHead>
                    <TableHead className="text-right">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {bank.priceObservations.map((observation) => (
                    <TableRow key={observation.id}>
                      <TableCell className="font-mono text-xs">
                        {observation.ontologyCode || observation.ontologyItemId}
                      </TableCell>
                      <TableCell className="max-w-xs min-w-64 whitespace-normal">
                        <p className="font-medium">
                          {observation.providerName || observation.source}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {observation.source.replaceAll("_", " ")}
                        </p>
                      </TableCell>
                      <TableCell className="max-w-xs min-w-48 whitespace-normal">
                        {observation.sourceRef?.startsWith("http") ? (
                          <a
                            className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"
                            href={observation.sourceRef}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Open official source
                            <ExternalLinkIcon className="size-3.5" />
                          </a>
                        ) : (
                          <span className="block max-w-48 text-sm break-all text-muted-foreground">
                            {observation.sourceRef || "No source reference"}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>{observation.date}</TableCell>
                      <TableCell>
                        {observation.priceScope || observation.unit} /{" "}
                        {observation.vatBasis || "unknown"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {observation.originalPrice == null
                          ? "—"
                          : formatMoney(observation.originalPrice)}
                      </TableCell>
                      <TableCell className="text-right font-medium tabular-nums">
                        {formatMoney(observation.priceNet)}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end">
                          <StatusBadge status={observation.approvalStatus} />
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </DataCard>
        </TabsContent>
      </Tabs>
      <Dialog
        open={selectedItem !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedItem(null)
        }}
      >
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {selectedItem?.name ?? "External price evidence"}
            </DialogTitle>
            <DialogDescription>
              Source prices and the exact aggregation used for the library
              value.
            </DialogDescription>
          </DialogHeader>
          {selectedItem ? (
            <div className="flex flex-col gap-4">
              <div className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2">
                <div>
                  <p className="text-xs text-muted-foreground">
                    External price used
                  </p>
                  <p className="mt-1 text-xl font-semibold tabular-nums">
                    {selectedItem.referencePriceNet == null
                      ? "—"
                      : formatMoney(selectedItem.referencePriceNet)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">
                    Aggregation method
                  </p>
                  <p className="mt-1 text-sm font-medium">
                    {externalPriceMethod(selectedItem, selectedObservations)}
                  </p>
                </div>
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Source</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead className="text-right">Net price</TableHead>
                    <TableHead className="text-right">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {selectedObservations.length ? (
                    selectedObservations.map((observation) => (
                      <TableRow key={observation.id}>
                        <TableCell>
                          {observation.sourceRef?.startsWith("http") ? (
                            <a
                              href={observation.sourceRef}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-primary hover:underline"
                            >
                              {observation.providerName || observation.source}
                              <ExternalLinkIcon className="size-3.5" />
                            </a>
                          ) : (
                            observation.providerName || observation.source
                          )}
                        </TableCell>
                        <TableCell>{observation.date}</TableCell>
                        <TableCell className="text-right font-medium tabular-nums">
                          {formatMoney(observation.priceNet)}
                        </TableCell>
                        <TableCell>
                          <div className="flex justify-end">
                            <StatusBadge status={observation.approvalStatus} />
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell
                        colSpan={4}
                        className="py-8 text-center text-muted-foreground"
                      >
                        No individual source observations are stored for this
                        item.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  )
}

function auditValue(event: NonNullable<ClaimWorkspace["auditEvents"]>[number]) {
  const afterStatus = event.after?.status
  if (typeof afterStatus === "string") return afterStatus.replaceAll("_", " ")
  const decision = event.payload?.decision
  if (typeof decision === "string") return decision.replaceAll("_", " ")
  return event.entity_type.replaceAll("_", " ")
}

export function AuditReportsScreen({
  workspace,
  onExport,
}: {
  workspace: ClaimWorkspace
  onExport: (format: "json" | "xlsx" | "sqlite") => void
}) {
  const events = workspace.auditEvents ?? []
  const versions = workspace.versions
  return (
    <>
      <ScreenHeading
        title="Audit & Reports"
        description={`Reproducible outputs stamped with policy ${versions?.policy ?? "unversioned"} and ontology ${versions?.ontology ?? "unversioned"}.`}
        action={<Badge variant="outline">{workspace.claim.id}</Badge>}
      />
      <div className="grid gap-6 lg:grid-cols-3">
        {[
          [
            "JSON evidence pack",
            "Machine-readable claim, extraction and challenge record",
            FileJson2Icon,
            "json",
          ],
          [
            "Excel review workbook",
            "Line-level mappings, comparables and calculation checks",
            FileSpreadsheetIcon,
            "xlsx",
          ],
          [
            "SQLite case database",
            "Portable pilot record and append-only audit trail",
            DatabaseIcon,
            "sqlite",
          ],
        ].map(([title, description, Icon, format]) => {
          const ExportIcon = Icon as typeof FileJson2Icon
          return (
            <Card key={String(format)}>
              <CardHeader>
                <span className="flex size-9 items-center justify-center rounded-md bg-muted">
                  <ExportIcon aria-hidden />
                </span>
                <CardTitle>{String(title)}</CardTitle>
                <CardDescription>{String(description)}</CardDescription>
              </CardHeader>
              <CardFooter>
                <Button
                  variant="outline"
                  onClick={() => onExport(format as "json" | "xlsx" | "sqlite")}
                >
                  <DownloadIcon data-icon="inline-start" />
                  Download {String(format).toUpperCase()}
                </Button>
              </CardFooter>
            </Card>
          )
        })}
      </div>
      <DataCard
        title="Audit history"
        description={`${events.length} append-only human and automated event${events.length === 1 ? "" : "s"}`}
      >
        <div className="max-h-[34rem] overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Event</TableHead>
                <TableHead>Value</TableHead>
                <TableHead>Record hash</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((event) => (
                <TableRow key={event.id}>
                  <TableCell>
                    {new Date(event.timestamp).toLocaleString("en-GB")}
                  </TableCell>
                  <TableCell>{event.actor}</TableCell>
                  <TableCell className="font-medium">
                    {event.action.replaceAll("_", " ")}
                  </TableCell>
                  <TableCell>{auditValue(event)}</TableCell>
                  <TableCell className="max-w-44 truncate font-mono text-xs text-muted-foreground">
                    {event.event_hash || "legacy unsealed event"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </DataCard>
      <Alert>
        <ShieldCheckIcon />
        <AlertTitle>Audit-ready by construction</AlertTitle>
        <AlertDescription>
          Extraction, model suggestion, handler correction, policy calculation
          and report versions remain separate, traceable records.
        </AlertDescription>
      </Alert>
    </>
  )
}
