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
import {
  isRowExpanded,
  toggleRowExpansion,
  NO_EXPANSION_CHOICES,
  type ExpansionChoices,
} from "./row-expansion"
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

/** Quantities, work units and hours are printed with up to 4 decimal places
 * (e.g. "1.0000", "14.0000") but that precision is noise to a reviewer.
 * Trim trailing zeros so 1.0000 reads as 1, 14.0000 as 14, and 1.4000 as
 * 1.4, while still showing genuine fractional values. Money keeps its own
 * formatter (`formatMaybeMoney`) since it must never drop trailing zeros. */
function formatQuantity(value: string | number | null | undefined) {
  const numeric = toNumber(value)
  if (numeric == null) return "—"
  return new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 4,
  }).format(numeric)
}

function breakdownSummaryLine(breakdown: SectionBreakdownPayload) {
  const label = lineItemTypeLabel(breakdown.line_item_type)
  const billed = formatMaybeMoney(breakdown.invoice_total)
  const assessedNumeric = toNumber(breakdown.assessment_total)
  const rowsTotalNumeric = toNumber(breakdown.rows_total)
  const rowsTotalSuffix =
    rowsTotalNumeric == null ? "" : ` (rows total ${formatMoney(rowsTotalNumeric)})`
  if (assessedNumeric == null) {
    return `Total ${label} ${billed} billed · not captured on the assessment${rowsTotalSuffix}`
  }
  const assessed = formatMoney(assessedNumeric)
  const difference = toNumber(breakdown.difference)
  if (difference == null || difference === 0) {
    return `Total ${label} ${billed} billed · ${assessed} assessed${rowsTotalSuffix} · matches`
  }
  const direction = difference > 0 ? "over" : "under"
  const magnitude = formatMoney(Math.abs(difference))
  return `Total ${label} ${billed} billed · ${assessed} assessed${rowsTotalSuffix} · ${magnitude} ${direction}`
}

/** The invoice sections the backend can resolve to a column the assessment
 * prints: the keys of `SECTION_TOTAL_FIELDS`
 * (`backend/app/services/engineer_assessment.py`). An invoice section outside
 * this set has no assessment counterpart at all; one inside it has a
 * counterpart column that may still be NULL on the document. Those are two
 * different answers and must not share a message. */
const RESOLVABLE_SECTION_TYPES = new Set([
  "parts",
  "paint_materials",
  "extras",
  "labour",
])

function hasBreakdownRows(breakdown: SectionBreakdownPayload) {
  return breakdown.breakdown_available !== false && breakdown.rows.length > 0
}

/** The four genuinely different reasons a rolled-up total shows no
 * breakdown rows. A reader has to be able to tell "the tool failed to line
 * these up" from "the document does not say", and the payload already
 * carries enough to separate them (backend `section_breakdown_for_invoice`):
 *
 * - `assessment_id` is null — nothing is paired to this invoice, so there is
 *   no document to split the total against;
 * - paired, but `line_item_type` is not one `SECTION_TOTAL_FIELDS` maps —
 *   the invoice section resolves to no assessment section at all (e.g. an
 *   unclassified "Total …" heading). This one really is the tool failing to
 *   line the two documents up;
 * - paired, the section *is* resolvable, but the assessment's own column is
 *   NULL — all four of `parts_net` / `paint_net` / `extras_net` /
 *   `labour_net` are nullable, so an invoice that prints "Total Extras" and
 *   an assessment with no extras section land here. Nothing failed: the
 *   document simply carries no such figure;
 * - paired, section total present, no rows — the assessment prints the
 *   section as a total with no line detail behind it. This is the real and
 *   correct outcome for "Total Paint / Materials Costs" on client formats 1
 *   and 7: `paint_net` is printed, but no operation carries the
 *   `paint_materials` code.
 *
 * Classification is on `line_item_type`, never on `assessment_total == null`:
 * the backend emits a null total for the second *and* the third case, so the
 * null alone cannot tell them apart.
 *
 * `breakdown_available` is `bool(rows)` on the backend, so it says *that*
 * there are no rows, never *why* — hence this second read of the payload. */
type BreakdownGap = "unpaired" | "unresolved" | "no-section-total" | "total-only"

function breakdownGap(breakdown: SectionBreakdownPayload): BreakdownGap | null {
  if (hasBreakdownRows(breakdown)) return null
  if (breakdown.assessment_id == null) return "unpaired"
  if (!RESOLVABLE_SECTION_TYPES.has(breakdown.line_item_type)) return "unresolved"
  if (toNumber(breakdown.assessment_total) == null) return "no-section-total"
  return "total-only"
}

const BREAKDOWN_GAP_MESSAGES: Record<
  BreakdownGap,
  { title: string; body: string }
> = {
  unpaired: {
    title: "No assessment is paired to this invoice",
    body: "There is no engineer assessment to split this total against. Check the pairing verdict on the assessment extracts table below.",
  },
  unresolved: {
    title: "This section resolves to no assessment category",
    body: "An assessment is paired, but the tool could not match this invoice section to any section the assessment prints, so it could not build a split.",
  },
  "no-section-total": {
    title: "The paired assessment prints no total for this section",
    body: "This section does map to one the assessment can print, but the paired document leaves it blank — it assessed nothing under this heading. There is no figure to split against; the extraction did not fail.",
  },
  "total-only": {
    title: "The assessment prints this section as a total only",
    body: "The paired assessment carries the section total but no line detail behind it. The document does not itemise it — the extraction did not fail.",
  },
}

/** `difference_convention` is emitted by the backend as the literal
 * `"invoice_total - assessment_total"`, but it is not declared on
 * `SectionBreakdownPayload` in `src/lib/api.ts` (a file this change does not
 * own). Read it off the payload defensively and say what the sign means in
 * words; the formula alone tells a claims handler nothing.
 *
 * Gated on there actually being a difference. With nothing paired, or a
 * section the assessment does not print, `difference` is null and the card
 * would otherwise assert the meaning of a sign on a number it never shows. */
function differenceConventionText(breakdown: SectionBreakdownPayload) {
  if (toNumber(breakdown.difference) == null) return null
  const convention = (breakdown as { difference_convention?: string | null })
    .difference_convention
  if (!convention) return null
  return `Difference is ${convention.replaceAll("_", " ")} — a positive difference means the repairer billed more than the engineer assessed.`
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
          tabIndex={0}
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
          tabIndex={0}
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

/** The split itself: which assessment line items add up to one rolled-up
 * invoice total. It opens by default -- this is the thing the client asked
 * to stop hunting for -- and keeps its own toggle so a long section can be
 * folded away again without collapsing the whole invoice. */
export function SectionBreakdownDetail({
  breakdown,
}: {
  breakdown: SectionBreakdownPayload
}) {
  const [open, setOpen] = useState(true)
  const gap = breakdownGap(breakdown)
  const conventionText = differenceConventionText(breakdown)
  const rowsId = `section-breakdown-rows-${breakdown.invoice_line_item_id}`
  return (
    <div className="my-2 rounded-md border bg-background p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="inline-flex items-center gap-2">
          {gap == null ? (
            <ExpandToggleButton
              expanded={open}
              onToggle={() => setOpen((current) => !current)}
              label={`the assessment breakdown for ${breakdown.description}`}
              controls={rowsId}
            />
          ) : null}
          <span className="text-sm font-medium">Assessment breakdown</span>
        </span>
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
      {conventionText ? (
        <p className="mt-1 text-xs text-muted-foreground">{conventionText}</p>
      ) : null}
      {gap != null ? (
        <div className="mt-2 rounded-md border border-dashed p-3">
          <p className="text-sm font-medium">
            {BREAKDOWN_GAP_MESSAGES[gap].title}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {BREAKDOWN_GAP_MESSAGES[gap].body}
          </p>
        </div>
      ) : open ? (
        <div id={rowsId} className="mt-2 overflow-x-auto">
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
                    {formatQuantity(row.work_units)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatQuantity(row.hours)}
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

export function InvoiceLinesTable({
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
            <Fragment key={line.id}>
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
                  {formatQuantity(line.quantity)}
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

export function AssessmentLinesTable({ lines }: { lines: AssessmentExtractLine[] }) {
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
                        tabIndex={0}
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
              {formatQuantity(line.work_units)}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {formatQuantity(line.hours)}
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

/** Row-level disclosures default to collapsed: a claim can carry 120+
 * reference rows across invoice and assessment lines, and expanding every
 * one by default would push the reviewer's price challenges below the
 * fold. Pass `defaultExpanded` as `true` to render every row pre-opened
 * (tests have no pointer to click the toggle), or as a predicate to open
 * only the rows worth opening -- see `AUTO_EXPAND_LINE_LIMIT`.
 *
 * State is held as each key's **absolute** choice, never as a "departure from
 * the default" -- see `row-expansion.ts` for why that distinction is the
 * whole point. */
function useRowExpansion(
  defaultExpanded: boolean | ((key: string) => boolean) = false
) {
  const [choices, setChoices] = useState<ExpansionChoices>(NO_EXPANSION_CHOICES)
  const defaultFor = (key: string) =>
    typeof defaultExpanded === "function" ? defaultExpanded(key) : defaultExpanded
  const isExpanded = (key: string) => isRowExpanded(choices, key, defaultFor(key))
  const toggle = (key: string) =>
    setChoices((previous) => toggleRowExpansion(previous, key, defaultFor(key)))
  return { isExpanded, toggle }
}

function ExpandToggleButton({
  expanded,
  onToggle,
  label,
  controls,
}: {
  expanded: boolean
  onToggle: () => void
  label: string
  controls: string
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={expanded ? `Collapse ${label}` : `Expand ${label}`}
      aria-expanded={expanded}
      aria-controls={controls}
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

/** `pair_key_verdicts` entries are objects, not strings -- spreading them into
 * a joined string printed `[object Object]` the moment anything wired the
 * field in. Take each verdict's own `text`. */
function pairReasonsText(assessment: AssessmentExtractPayload) {
  const reasons = [
    ...assessment.pair_reasons,
    ...(assessment.pair_key_verdicts ?? []).map((verdict) => verdict.text),
  ]
  return reasons.length > 0 ? reasons.join("; ") : "No pairing evidence recorded."
}

/** Above this many invoice lines an invoice is not opened automatically.
 * Auto-expansion exists to put the split in front of the reader; dumping a
 * 300-line itemised invoice into the page would bury the very breakdown it
 * was opened for, and the reader can still open it by hand. */
const AUTO_EXPAND_LINE_LIMIT = 40

/** An invoice that rolls its costs up into section totals is exactly the
 * case the client asked to see without hunting -- "total parts in invoice =
 * 110 means from the engineer estimate we shud show what all parts line
 * items r taken exactly to get tht total parts cost". Such a row opens
 * itself, and `SectionBreakdownDetail` inside it opens too, so the split is
 * on screen with no clicks. An invoice with no rolled-up total has no split
 * to show, so it stays collapsed.
 *
 * The breakdown must actually *resolve* -- carry rows -- not merely exist.
 * `get_claim_extracts` emits a breakdown for every `is_section_total` line
 * unconditionally, including when no assessment is paired to the invoice at
 * all, so "a breakdown exists" is true of every rolled-up invoice in the
 * case. Auto-expanding on that alone meant uploading invoices before any
 * estimate blew every invoice open onto four "No assessment is paired to this
 * invoice" boxes -- the opposite of putting the split in front of the
 * reader. */
function hasVisibleSectionSplit(
  invoice: InvoiceExtractPayload,
  breakdowns: SectionBreakdownPayload[]
) {
  if (invoice.lines.length > AUTO_EXPAND_LINE_LIMIT) return false
  return invoice.lines.some(
    (line) =>
      line.is_section_total &&
      breakdowns.some(
        (breakdown) =>
          breakdown.invoice_id === invoice.invoice_id &&
          breakdown.line_item_type === (line.line_item_type ?? "") &&
          hasBreakdownRows(breakdown)
      )
  )
}

/** How a table decides which rows start open.
 *
 * Three named states rather than `defaultExpanded?: boolean`. Under the
 * boolean there were two different spellings of "not pre-expanded" --
 * `undefined` meant "apply the auto-expand rule", `false` meant "open
 * nothing" -- and nothing on the type said which was which, or that they
 * differed at all. A caller that meant "leave them alone" had to know that
 * omitting the prop did the opposite of passing `false`. */
export type ExtractsExpansion = "auto" | "all" | "none"

export function InvoiceExtractsTable({
  invoices,
  breakdowns,
  expansion = "auto",
}: {
  invoices: InvoiceExtractPayload[]
  breakdowns: SectionBreakdownPayload[]
  /** `auto` opens only the invoices with a split worth showing; `all` opens
   * every invoice (tests have no pointer to click a toggle); `none` opens
   * none. */
  expansion?: ExtractsExpansion
}) {
  const autoExpanded = new Set(
    invoices
      .filter((invoice) => hasVisibleSectionSplit(invoice, breakdowns))
      .map((invoice) => invoice.invoice_id)
  )
  const { isExpanded, toggle } = useRowExpansion(
    expansion === "auto"
      ? (key: string) => autoExpanded.has(key)
      : expansion === "all"
  )
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-8">
            <span className="sr-only">Expand line items</span>
          </TableHead>
          <TableHead>Invoice number</TableHead>
          <TableHead>Vehicle make</TableHead>
          <TableHead>Vehicle model</TableHead>
          <TableHead>Registration</TableHead>
          <TableHead>Claim number</TableHead>
          <TableHead>Policy number</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {invoices.map((invoice) => {
          const key = invoice.invoice_id
          const expanded = isExpanded(key)
          const detailId = `invoice-extract-detail-${key}`
          const breakdownsByType = new Map(
            breakdowns
              .filter((breakdown) => breakdown.invoice_id === invoice.invoice_id)
              .map((breakdown) => [breakdown.line_item_type, breakdown] as const)
          )
          return (
            <Fragment key={key}>
              <TableRow>
                <TableCell>
                  <ExpandToggleButton
                    expanded={expanded}
                    onToggle={() => toggle(key)}
                    label={`lines for invoice ${invoice.invoice_number ?? key}`}
                    controls={detailId}
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
                <TableRow id={detailId}>
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

export function AssessmentExtractsTable({
  assessments,
  expansion = "auto",
}: {
  assessments: AssessmentExtractPayload[]
  /** There is no auto-expand rule on this side -- the split already lives on
   * the invoice, and a 120-operation report would push everything else off
   * the page -- so `auto` and `none` are the same thing here. */
  expansion?: ExtractsExpansion
}) {
  const { isExpanded, toggle } = useRowExpansion(expansion === "all")
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-8">
            <span className="sr-only">Expand operations</span>
          </TableHead>
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
        {assessments.map((assessment) => {
          const key = assessment.assessment_id
          const expanded = isExpanded(key)
          const detailId = `assessment-extract-detail-${key}`
          return (
            <Fragment key={key}>
              <TableRow>
                <TableCell>
                  <ExpandToggleButton
                    expanded={expanded}
                    onToggle={() => toggle(key)}
                    label={`lines for assessment ${assessment.assessment_number ?? key}`}
                    controls={detailId}
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
                  <div className="flex flex-col items-start gap-1">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Badge
                          tabIndex={0}
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
                      <TooltipContent>{pairReasonsText(assessment)}</TooltipContent>
                    </Tooltip>
                    <p className="max-w-xs text-xs text-muted-foreground">
                      {pairReasonsText(assessment)}
                    </p>
                  </div>
                </TableCell>
              </TableRow>
              {expanded ? (
                <TableRow id={detailId}>
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
  if (
    extracts == null ||
    (extracts.invoice_extracts.length === 0 &&
      extracts.assessment_extracts.length === 0)
  ) {
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
              ) : (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  No invoice or assessment extracts are available for this
                  claim yet.
                </p>
              )}
            </CardContent>
          </CollapsibleContent>
        </Collapsible>
      </Card>
    )
  }

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
            <div>
              <h3 className="text-sm font-semibold">Invoice extracts</h3>
              <div className="mt-2 overflow-x-auto rounded-lg border">
                <InvoiceExtractsTable
                  invoices={extracts.invoice_extracts}
                  breakdowns={extracts.section_breakdowns}
                />
              </div>
            </div>
            <div>
              <h3 className="text-sm font-semibold">Assessment extracts</h3>
              <div className="mt-2 overflow-x-auto rounded-lg border">
                <AssessmentExtractsTable
                  assessments={extracts.assessment_extracts}
                />
              </div>
            </div>
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}
