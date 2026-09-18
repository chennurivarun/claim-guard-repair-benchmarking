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
    return `Total ${label} ${billed} billed · not captured on the engineer assessment${rowsTotalSuffix}`
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
  // The body used to point at "the assessment extracts table below"; the
  // split now renders on benchmark analysis, where there is no such table,
  // so it names the screen that carries the pairing instead.
  unpaired: {
    title: "No engineer assessment is paired to this invoice",
    body: "There is no engineer assessment to split this total against. Check the pairing on Document intelligence.",
  },
  unresolved: {
    title: "This section resolves to no engineer assessment category",
    body: "An engineer assessment is paired, but the tool could not match this invoice section to any section the engineer assessment prints, so it could not build a split.",
  },
  "no-section-total": {
    title: "The paired engineer assessment prints no total for this section",
    body: "This section does map to one the engineer assessment can print, but the paired document leaves it blank — it assessed nothing under this heading. There is no figure to split against; the extraction did not fail.",
  },
  "total-only": {
    title: "The engineer assessment prints this section as a total only",
    body: "The paired engineer assessment carries the section total but no line detail behind it. The document does not itemise it — the extraction did not fail.",
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

/** The other document's number, in the association columns the client asked
 * for (§3.4 / §3.5 of the 17 Sep walkthrough). A missing association is not
 * a missing *value*: every other identity column prints an em dash for "the
 * document did not print this", and reusing it here would say the pairing
 * key failed to extract when what actually happened is that nothing is
 * paired. So it gets words. */
function AssociationCell({ number }: { number: string | null }) {
  if (number) return <span className="font-medium">{number}</span>
  return <span className="text-muted-foreground">Not paired</span>
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

/** The split itself: which engineer assessment line items add up to one
 * rolled-up invoice total. It opens by default and keeps its own toggle so a
 * long section can be folded away again.
 *
 * Mounted on **benchmark analysis** (`screens-benchmark-analysis.tsx`), and
 * only there. It used to render inside the invoice extracts table, under
 * each rolled-up total. On the 17 Sep walkthrough the client ruled that out
 * for *that* screen -- "if the invoice is not talking about parts, you won't
 * show the part line items there. You would show those parts in the
 * assessment section, which is below" -- because Document intelligence
 * exists to prove that both documents were read and mapped, and each table
 * must therefore show only what its own document prints. Benchmark analysis
 * is where she said "now we are able to combine them when we do the
 * analysis". */
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
              label={`the engineer assessment breakdown for ${breakdown.description}`}
              controls={rowsId}
            />
          ) : null}
          <span className="text-sm font-medium">
            Engineer assessment breakdown
          </span>
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
            ? "Not captured on the engineer assessment"
            : breakdown.matches
              ? "Matches engineer assessment"
              : "Does not match engineer assessment"}
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

/** The invoice's own lines and nothing else. For a rolled-up invoice that is
 * the three or four section totals it prints; the assessment rows behind
 * those totals belong to the assessment table below, and to benchmark
 * analysis after that -- see the note on `SectionBreakdownDetail`. */
export function InvoiceLinesTable({ lines }: { lines: InvoiceExtractLine[] }) {
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
        {lines.map((line) => (
          <TableRow key={line.id}>
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
        ))}
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
 * (tests have no pointer to click the toggle). The predicate form is kept
 * for a table that wants a per-row rule; no caller has one today -- see
 * `ExtractsExpansion` for why the invoice side's rule was removed.
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

/** How a table decides which rows start open.
 *
 * Three named states rather than `defaultExpanded?: boolean`. Under the
 * boolean there were two different spellings of "not pre-expanded" --
 * `undefined` meant "apply the auto-expand rule", `false` meant "open
 * nothing" -- and nothing on the type said which was which, or that they
 * differed at all. A caller that meant "leave them alone" had to know that
 * omitting the prop did the opposite of passing `false`.
 *
 * `auto` no longer opens anything on either table. It existed on the invoice
 * side solely to put the assessment split in front of the reader without a
 * click; with the split gone from this screen (see `SectionBreakdownDetail`)
 * the predicate had nothing left to reveal, so the rule, its line limit and
 * the `breakdowns` prop that fed it were removed rather than left running
 * against nothing. `auto` is kept as the default so callers keep reading as
 * "whatever this table thinks is right", and so benchmark analysis can give
 * it a rule again. */
export type ExtractsExpansion = "auto" | "all" | "none"

export function InvoiceExtractsTable({
  invoices,
  expansion = "auto",
}: {
  invoices: InvoiceExtractPayload[]
  /** `all` opens every invoice (tests have no pointer to click a toggle);
   * `auto` and `none` both open nothing. */
  expansion?: ExtractsExpansion
}) {
  const { isExpanded, toggle } = useRowExpansion(expansion === "all")
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-8">
            <span className="sr-only">Expand line items</span>
          </TableHead>
          <TableHead>Invoice number</TableHead>
          <TableHead>Associated assessment number</TableHead>
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
                  <AssociationCell number={invoice.paired_assessment_number} />
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
                  <TableCell colSpan={8} className="bg-muted/30 p-3">
                    {invoice.lines.length > 0 ? (
                      <InvoiceLinesTable lines={invoice.lines} />
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
          <TableHead>Associated invoice number</TableHead>
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
                    label={`lines for engineer assessment ${assessment.assessment_number ?? key}`}
                    controls={detailId}
                  />
                </TableCell>
                <TableCell className="font-medium">
                  {assessment.assessment_number ?? "—"}
                </TableCell>
                <TableCell>
                  <AssociationCell
                    number={assessment.paired_invoice_number}
                  />
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
                  <TableCell colSpan={9} className="bg-muted/30 p-3">
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

/** `scopeLabel` names the source the extracts were fetched for (the fetch
 * itself is scoped by `intake_group`); omitted, the section reads as it
 * always did -- which is what Review findings still renders. */
export function ExtractsSection({
  extracts,
  loading,
  error,
  scopeLabel,
}: {
  extracts: ClaimExtractsPayload | null
  loading: boolean
  error: string | null
  scopeLabel?: string
}) {
  const [open, setOpen] = useState(true)
  const scopeSentence = scopeLabel ? ` Showing ${scopeLabel} only.` : null
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
                <CardTitle>Invoice and engineer assessment extracts</CardTitle>
                <CardDescription>
                  The two standardised tables from the invoice and engineer
                  assessment documents, kept separate. Each table shows only
                  what its own document contains.{scopeSentence}
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
                  Loading invoice and engineer assessment extracts…
                </p>
              ) : (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  No invoice or engineer assessment extracts are available for
                  this claim yet.
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
              <CardTitle>Invoice and engineer assessment extracts</CardTitle>
              <CardDescription>
                The two standardised tables from the invoice and engineer
                assessment documents, kept separate. Each table shows only what
                its own document contains.{scopeSentence}
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
            {/* The client dictated both headings on the 17 Sep walkthrough.
                Each names the document the table is built from and the
                association it carries to the other one -- the two facts the
                screen exists to evidence. `section_breakdowns` is still on
                the payload and still emitted by the backend; nothing on this
                screen reads it, and benchmark analysis will. */}
            <div>
              <h3 className="text-sm font-semibold">
                Invoice extracts and associated engineer assessment
              </h3>
              <div className="mt-2 overflow-x-auto rounded-lg border">
                <InvoiceExtractsTable invoices={extracts.invoice_extracts} />
              </div>
            </div>
            <div>
              <h3 className="text-sm font-semibold">
                Engineer assessment extracts and invoice association
              </h3>
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
