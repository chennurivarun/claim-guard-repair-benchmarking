import { Fragment, useState } from "react"
import {
  AlertCircleIcon,
  ChevronDownIcon,
  ChevronRightIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

import { formatMoney } from "./format"
import type {
  AssessmentExtractLine,
  AssessmentExtractPayload,
  ClaimExtractsPayload,
  InvoiceExtractLine,
  InvoiceExtractPayload,
  SectionBreakdownPayload,
} from "@/lib/api"

/** ``line_item_type`` is an open vocabulary (backend/app/domain/line_item_type.py):
 * anything not in this map falls back to a title-cased slug, matching new
 * sections the client adds without a frontend change. */
const LINE_ITEM_TYPE_LABELS: Record<string, string> = {
  parts: "Parts",
  extras: "Extras",
  labour: "Labour",
  paint: "Paint",
  paint_materials: "Paint & materials",
  specialist_operation: "Specialist operation",
  sundry: "Sundry",
  discount: "Discount",
  unknown: "Unclassified",
}

function lineItemTypeLabel(type: string | null | undefined) {
  if (!type) return "Unclassified"
  return (
    LINE_ITEM_TYPE_LABELS[type] ??
    type
      .split("_")
      .filter(Boolean)
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ")
  )
}

function toNumber(value: string | number | null | undefined) {
  if (value == null || value === "") return null
  const parsed = typeof value === "number" ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function formatMaybeMoney(value: string | number | null | undefined) {
  const numeric = toNumber(value)
  return numeric == null ? "—" : formatMoney(numeric)
}

function breakdownSummaryLine(breakdown: SectionBreakdownPayload) {
  const label = lineItemTypeLabel(breakdown.line_item_type)
  const billed = formatMaybeMoney(breakdown.invoice_total)
  const assessedNumeric = toNumber(breakdown.assessment_total)
  if (assessedNumeric == null) {
    return `Total ${label} ${billed} billed · not captured on the assessment`
  }
  const assessed = formatMoney(assessedNumeric)
  const difference = toNumber(breakdown.difference)
  if (difference == null || difference === 0) {
    return `Total ${label} ${billed} billed · ${assessed} assessed · matches`
  }
  const direction = difference > 0 ? "over" : "under"
  const magnitude = formatMoney(Math.abs(difference))
  return `Total ${label} ${billed} billed · ${assessed} assessed · ${magnitude} ${direction}`
}

function FieldSourceBadge({
  source,
}: {
  source?: { label: string; value: string | number } | undefined
}) {
  if (!source) return null
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge
          variant="outline"
          className="border-sky-300 px-1.5 py-0 text-[10px] font-normal text-sky-700 dark:border-sky-900 dark:text-sky-300"
        >
          from assessment
        </Badge>
      </TooltipTrigger>
      <TooltipContent>{source.label}</TooltipContent>
    </Tooltip>
  )
}

function IdentityCell({
  value,
  source,
}: {
  value: string | null
  source?: { label: string; value: string | number } | undefined
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={value ? undefined : "text-muted-foreground"}>
        {value ?? "—"}
      </span>
      <FieldSourceBadge source={source} />
    </span>
  )
}

function SectionTotalBadge() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge
          variant="outline"
          className="border-amber-300 text-amber-700 dark:border-amber-900 dark:text-amber-300"
        >
          Rolled-up total
        </Badge>
      </TooltipTrigger>
      <TooltipContent>
        Printed as a section total on the invoice, not an itemised line.
      </TooltipContent>
    </Tooltip>
  )
}

function SectionBreakdownDetail({
  breakdown,
}: {
  breakdown: SectionBreakdownPayload
}) {
  return (
    <div className="my-2 rounded-md border bg-background p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">Assessment breakdown</p>
        <Badge
          variant={
            breakdown.matches == null
              ? "outline"
              : breakdown.matches
                ? "success"
                : "destructive"
          }
        >
          {breakdown.matches == null
            ? "Not captured on assessment"
            : breakdown.matches
              ? "Matches assessment"
              : "Does not match assessment"}
        </Badge>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        {breakdownSummaryLine(breakdown)}
      </p>
      {breakdown.rows.length > 0 ? (
        <div className="mt-2 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Description</TableHead>
                <TableHead className="text-right">Work units</TableHead>
                <TableHead className="text-right">Hours</TableHead>
                <TableHead className="text-right">Unit price</TableHead>
                <TableHead className="text-right">Total</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {breakdown.rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>{row.description}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.work_units ?? "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.hours ?? "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMaybeMoney(row.unit_price_net)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMaybeMoney(row.total_net)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </div>
  )
}

function InvoiceLinesTable({
  lines,
  breakdownsByType,
}: {
  lines: InvoiceExtractLine[]
  breakdownsByType: Map<string, SectionBreakdownPayload>
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Seq</TableHead>
          <TableHead>Section</TableHead>
          <TableHead>Description</TableHead>
          <TableHead className="text-right">Qty</TableHead>
          <TableHead className="text-right">Unit price</TableHead>
          <TableHead className="text-right">Line total</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {lines.map((line) => {
          const breakdown = line.is_section_total
            ? breakdownsByType.get(line.line_item_type ?? "")
            : undefined
          return (
            <Fragment key={line.sequence_no}>
              <TableRow>
                <TableCell className="text-muted-foreground">
                  {line.sequence_no}
                </TableCell>
                <TableCell>
                  <span className="inline-flex items-center gap-2">
                    {lineItemTypeLabel(line.line_item_type)}
                    {line.is_section_total ? <SectionTotalBadge /> : null}
                  </span>
                </TableCell>
                <TableCell>{line.description}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {line.quantity ?? "—"}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatMaybeMoney(line.unit_price)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatMaybeMoney(line.line_total)}
                </TableCell>
              </TableRow>
              {breakdown ? (
                <TableRow>
                  <TableCell colSpan={6} className="bg-muted/20">
                    <SectionBreakdownDetail breakdown={breakdown} />
                  </TableCell>
                </TableRow>
              ) : null}
            </Fragment>
          )
        })}
      </TableBody>
    </Table>
  )
}

function AssessmentLinesTable({ lines }: { lines: AssessmentExtractLine[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Seq</TableHead>
          <TableHead>Section</TableHead>
          <TableHead>Description</TableHead>
          <TableHead className="text-right">Work units</TableHead>
          <TableHead className="text-right">Hours</TableHead>
          <TableHead className="text-right">Unit price</TableHead>
          <TableHead className="text-right">Line total</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {lines.map((line) => (
          <TableRow key={line.sequence_no}>
            <TableCell className="text-muted-foreground">
              {line.sequence_no}
            </TableCell>
            <TableCell>{lineItemTypeLabel(line.line_item_type)}</TableCell>
            <TableCell>
              <span className="inline-flex items-center gap-1.5">
                {line.description}
                {line.price_derived ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Badge
                        variant="outline"
                        className="px-1.5 py-0 text-[10px] font-normal"
                      >
                        rate-derived
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent>
                      Priced from work units × the labour or paint rate; not
                      printed on the report.
                    </TooltipContent>
                  </Tooltip>
                ) : null}
              </span>
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {line.work_units ?? "—"}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {line.hours ?? "—"}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {formatMaybeMoney(line.unit_price)}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {formatMaybeMoney(line.line_total)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function useRowExpansion() {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const isExpanded = (key: string) => !collapsed.has(key)
  const toggle = (key: string) => {
    setCollapsed((previous) => {
      const next = new Set(previous)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }
  return { isExpanded, toggle }
}

function ExpandToggleButton({
  expanded,
  onToggle,
  label,
}: {
  expanded: boolean
  onToggle: () => void
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={expanded ? `Collapse ${label}` : `Expand ${label}`}
      className="text-muted-foreground transition-colors hover:text-foreground"
    >
      {expanded ? (
        <ChevronDownIcon className="size-4" />
      ) : (
        <ChevronRightIcon className="size-4" />
      )}
    </button>
  )
}

function InvoiceExtractsTable({
  invoices,
  breakdowns,
}: {
  invoices: InvoiceExtractPayload[]
  breakdowns: SectionBreakdownPayload[]
}) {
  const { isExpanded, toggle } = useRowExpansion()
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-8" />
          <TableHead>Invoice number</TableHead>
          <TableHead>Vehicle make</TableHead>
          <TableHead>Vehicle model</TableHead>
          <TableHead>Registration</TableHead>
          <TableHead>Claim number</TableHead>
          <TableHead>Policy number</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {invoices.map((invoice, index) => {
          const key = invoice.invoice_number ?? `invoice-${index}`
          const expanded = isExpanded(key)
          const breakdownsByType = new Map(
            breakdowns
              .filter(
                (breakdown) => breakdown.invoice_number === invoice.invoice_number
              )
              .map((breakdown) => [breakdown.line_item_type, breakdown] as const)
          )
          return (
            <Fragment key={key}>
              <TableRow>
                <TableCell>
                  <ExpandToggleButton
                    expanded={expanded}
                    onToggle={() => toggle(key)}
                    label={`lines for invoice ${invoice.invoice_number ?? index}`}
                  />
                </TableCell>
                <TableCell className="font-medium">
                  {invoice.invoice_number ?? "—"}
                </TableCell>
                <TableCell>
                  <IdentityCell
                    value={invoice.vehicle_make}
                    source={invoice.field_sources?.make}
                  />
                </TableCell>
                <TableCell>
                  <IdentityCell
                    value={invoice.vehicle_model}
                    source={invoice.field_sources?.model}
                  />
                </TableCell>
                <TableCell>
                  <IdentityCell
                    value={invoice.vehicle_registration}
                    source={invoice.field_sources?.registration}
                  />
                </TableCell>
                <TableCell>
                  <IdentityCell
                    value={invoice.claim_number}
                    source={invoice.field_sources?.claim_reference}
                  />
                </TableCell>
                <TableCell>
                  <IdentityCell
                    value={invoice.policy_number}
                    source={invoice.field_sources?.policy_number}
                  />
                </TableCell>
              </TableRow>
              {expanded ? (
                <TableRow>
                  <TableCell colSpan={7} className="bg-muted/30 p-3">
                    {invoice.lines.length > 0 ? (
                      <InvoiceLinesTable
                        lines={invoice.lines}
                        breakdownsByType={breakdownsByType}
                      />
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        No line items extracted for this invoice.
                      </p>
                    )}
                  </TableCell>
                </TableRow>
              ) : null}
            </Fragment>
          )
        })}
      </TableBody>
    </Table>
  )
}

function AssessmentExtractsTable({
  assessments,
}: {
  assessments: AssessmentExtractPayload[]
}) {
  const { isExpanded, toggle } = useRowExpansion()
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-8" />
          <TableHead>Assessment number</TableHead>
          <TableHead>Vehicle make</TableHead>
          <TableHead>Vehicle model</TableHead>
          <TableHead>Registration</TableHead>
          <TableHead>Claim number</TableHead>
          <TableHead>Policy number</TableHead>
          <TableHead>Pairing</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {assessments.map((assessment, index) => {
          const key = assessment.assessment_number ?? `assessment-${index}`
          const expanded = isExpanded(key)
          return (
            <Fragment key={key}>
              <TableRow>
                <TableCell>
                  <ExpandToggleButton
                    expanded={expanded}
                    onToggle={() => toggle(key)}
                    label={`lines for assessment ${assessment.assessment_number ?? index}`}
                  />
                </TableCell>
                <TableCell className="font-medium">
                  {assessment.assessment_number ?? "—"}
                </TableCell>
                <TableCell>{assessment.vehicle_make ?? "—"}</TableCell>
                <TableCell>{assessment.vehicle_model ?? "—"}</TableCell>
                <TableCell>{assessment.vehicle_registration ?? "—"}</TableCell>
                <TableCell>{assessment.claim_number ?? "—"}</TableCell>
                <TableCell>{assessment.policy_number ?? "—"}</TableCell>
                <TableCell>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Badge
                        variant={
                          assessment.pair_status === "paired"
                            ? "success"
                            : "secondary"
                        }
                      >
                        {assessment.pair_status === "paired"
                          ? `Paired · ${assessment.paired_invoice_number ?? "invoice"}`
                          : "Unpaired"}
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent>
                      {assessment.pair_reasons.length > 0
                        ? assessment.pair_reasons.join("; ")
                        : "No pairing evidence recorded."}
                    </TooltipContent>
                  </Tooltip>
                </TableCell>
              </TableRow>
              {expanded ? (
                <TableRow>
                  <TableCell colSpan={8} className="bg-muted/30 p-3">
                    {assessment.lines.length > 0 ? (
                      <AssessmentLinesTable lines={assessment.lines} />
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        No operations extracted for this assessment.
                      </p>
                    )}
                  </TableCell>
                </TableRow>
              ) : null}
            </Fragment>
          )
        })}
      </TableBody>
    </Table>
  )
}

export function ExtractsSection({
  extracts,
  loading,
  error,
}: {
  extracts: ClaimExtractsPayload | null
  loading: boolean
  error: string | null
}) {
  const [open, setOpen] = useState(true)
  const isEmpty =
    !extracts ||
    (extracts.invoice_extracts.length === 0 &&
      extracts.assessment_extracts.length === 0)

  return (
    <Card>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>Invoice and assessment extracts</CardTitle>
              <CardDescription>
                The two standardised tables from the invoice and assessment
                documents, kept separate. Line items are nested under each
                document.
              </CardDescription>
            </div>
            <CollapsibleTrigger asChild>
              <button
                type="button"
                className="group/extracts inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                {open ? "Hide" : "Show"}
                <ChevronRightIcon
                  className="size-4 transition-transform group-data-[state=open]/extracts:rotate-90"
                  aria-hidden
                />
              </button>
            </CollapsibleTrigger>
          </div>
        </CardHeader>
        <CollapsibleContent>
          <CardContent className="space-y-6">
            {error ? (
              <Alert variant="destructive">
                <AlertCircleIcon />
                <AlertTitle>Extracts could not be loaded</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : loading ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                Loading invoice and assessment extracts…
              </p>
            ) : isEmpty ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No invoice or assessment extracts are available for this claim
                yet.
              </p>
            ) : (
              <>
                <div>
                  <h3 className="text-sm font-semibold">Invoice extracts</h3>
                  <div className="mt-2 overflow-x-auto rounded-lg border">
                    <InvoiceExtractsTable
                      invoices={extracts!.invoice_extracts}
                      breakdowns={extracts!.section_breakdowns}
                    />
                  </div>
                </div>
                <div>
                  <h3 className="text-sm font-semibold">
                    Assessment extracts
                  </h3>
                  <div className="mt-2 overflow-x-auto rounded-lg border">
                    <AssessmentExtractsTable
                      assessments={extracts!.assessment_extracts}
                    />
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}
