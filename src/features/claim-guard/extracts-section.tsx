import { Fragment, useEffect, useState } from "react"
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

import {
  assessmentPartner,
  backToInvoice,
  breakdownGap,
  dismissNotice,
  filterSectionOperations,
  findSectionBreakdown,
  followAssessmentNumber,
  followInvoiceNumber,
  followSectionTotal,
  invoicePartner,
  linkRowIds,
  NO_LINK,
  releaseLink,
  showAllOperations,
  type AssessmentLink,
  type BreakdownGap,
  type ExtractsLinkState,
  type LinkGap,
  type Partner,
} from "./extracts-link"
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

/** The four gap states and their wording are the ones agreed with the
 * client; the classification lives in `extracts-link.ts` (`breakdownGap`) so
 * the link between the two tables reads the same payload the same way. */
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
    title: "No engineer assessment total was extracted for this section",
    body: "The extracted engineer assessment has no total for this heading. Check the original engineer assessment to see whether the figure is absent or was missed during extraction.",
  },
  "total-only": {
    title: "Engineer assessment total found, but no detailed rows extracted",
    body: "The engineer assessment is paired and its section total was read, but no detailed rows were extracted for this section. Check the original engineer assessment. If it lists parts or operations, these details were missed; use Retry engineer assessment details on Upload documents when the engineer assessment has no detail rows.",
  },
}

/** What a click on a rolled-up total says instead of jumping. The four
 * breakdown gaps keep their agreed wording; the fifth exists only on a screen
 * scoped to one source, where the paired engineer assessment was uploaded
 * under another source and has no row here to jump to. */
const LINK_GAP_MESSAGES: Record<LinkGap, { title: string; body: string }> = {
  ...BREAKDOWN_GAP_MESSAGES,
  "off-screen": {
    title: "The paired engineer assessment is not on this screen",
    body: "This screen shows one source's documents only, and the engineer assessment paired to this invoice was uploaded under a different source. Open that source to see its operations.",
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
 * paired. So it gets words.
 *
 * "Paired" and "has a number" are two different facts. Format 1's invoice
 * prints no invoice number, and its engineer assessment is paired to it all
 * the same; reading the missing number as a missing pair put "Not paired"
 * beside a Pairing badge that said "Paired". A paired row never reads "Not
 * paired": it says the partner's number was not extracted, and stays a link
 * to the partner's row whenever that row is on this screen. */
function AssociationCell({
  partner,
  documentLabel,
  onFollow,
}: {
  partner: Partner
  documentLabel: "invoice" | "engineer assessment"
  onFollow?: () => void
}) {
  if (!partner.paired) {
    return <span className="text-muted-foreground">Not paired</span>
  }
  const text = partner.number ?? `Paired · ${documentLabel} number not extracted`
  const tone = partner.number ? "font-medium" : "text-muted-foreground"
  if (onFollow && partner.onScreen) {
    return (
      <button
        type="button"
        onClick={onFollow}
        aria-label={`Go to the paired ${documentLabel} ${partner.number ?? "(number not extracted)"}`}
        className={`${tone} text-left underline decoration-dotted underline-offset-4 hover:text-foreground hover:decoration-solid`}
      >
        {text}
      </button>
    )
  }
  return (
    <span className={tone}>
      {text}
      {partner.id != null && !partner.onScreen ? (
        <span className="block text-xs font-normal text-muted-foreground">
          Not on this screen
        </span>
      ) : null}
    </span>
  )
}

/** Everything the two tables need to link to each other. Optional on both
 * tables: without it they render exactly as they did before the link, which
 * is how benchmark analysis and the older tests mount them. */
export interface ExtractsLinking {
  extracts: ClaimExtractsPayload
  state: ExtractsLinkState
  onSectionTotal: (invoiceId: string, invoiceLineId: string) => void
  onAssessmentNumber: (invoiceId: string) => void
  onInvoiceNumber: (assessmentId: string) => void
  onShowAll: () => void
  onBack: () => void
  onRelease: () => void
  onDismissNotice: () => void
}

function invoiceLabel(number: string | null | undefined) {
  return number ? `invoice ${number}` : "the invoice (number not extracted)"
}

/** "3 parts", "3 labour and paintwork operations". An invoice's Total Labour
 * pays for both labour and paintwork (backend `SECTION_OPERATION_CATEGORIES`)
 * and the noun says so, rather than calling paintwork rows "labour". */
function sectionOperationsNoun(lineItemType: string, count: number) {
  const plural = count === 1 ? "" : "s"
  if (lineItemType === "parts") return count === 1 ? "part" : "parts"
  if (lineItemType === "labour") return `labour and paintwork operation${plural}`
  return `${lineItemTypeLabel(lineItemType).toLowerCase()} operation${plural}`
}

/** Sits at the top of the linked engineer assessment's operations -- where
 * the jump lands -- and says what the rows below are filtered to and why,
 * with the way out (every operation) and the way back (the invoice line the
 * reader came from). */
function LinkBanner({
  link,
  invoiceNumber,
  shown,
  total,
  onShowAll,
  onBack,
}: {
  link: AssessmentLink
  invoiceNumber: string | null
  shown: number
  total: number
  onShowAll: () => void
  onBack: () => void
}) {
  const invoice = invoiceLabel(invoiceNumber)
  const { breakdown } = link
  return (
    <div
      role="status"
      // Capped and stacked, not spread across the row: the cell spans a
      // table wider than the screen, and controls pushed to its far end
      // would sit off-screen where the jump lands.
      className="mb-3 max-w-2xl space-y-3 rounded-md border border-sky-300 bg-sky-50 p-3 text-sm whitespace-normal dark:border-sky-900 dark:bg-sky-950/40"
    >
      <div className="space-y-1">
        {breakdown ? (
          <>
            <p className="font-medium">
              Showing the {shown}{" "}
              {sectionOperationsNoun(breakdown.line_item_type, shown)} behind{" "}
              {breakdown.description} {formatMaybeMoney(breakdown.invoice_total)}{" "}
              on {invoice}.
            </p>
            <p className="text-muted-foreground">
              {breakdown.line_item_type === "labour"
                ? "An invoice's Total Labour pays for both labour and paintwork, so both are shown. "
                : null}
              The other {total - shown} operation{total - shown === 1 ? "" : "s"}{" "}
              on this engineer assessment are hidden.
            </p>
          </>
        ) : (
          <p className="font-medium">
            Showing all {total} operation{total === 1 ? "" : "s"} of the
            engineer assessment paired to {invoice}.
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {breakdown ? (
          <button
            type="button"
            onClick={onShowAll}
            className="rounded-md border bg-background px-2.5 py-1 font-medium hover:bg-muted"
          >
            Show all {total} operations
          </button>
        ) : null}
        <button
          type="button"
          onClick={onBack}
          className="rounded-md border bg-background px-2.5 py-1 font-medium hover:bg-muted"
        >
          Back to {breakdown ? `${breakdown.description} on ` : ""}
          {invoice}
        </button>
      </div>
    </div>
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
 * analysis after that -- see the note on `SectionBreakdownDetail`.
 *
 * With `linking`, a rolled-up total's description is the way down to those
 * rows: clicking it jumps to the paired engineer assessment in the table
 * below, filtered to that section. When there is nothing to jump to, the
 * reason is said here, under the line that was clicked. */
export function InvoiceLinesTable({
  lines,
  invoiceId,
  linking,
}: {
  lines: InvoiceExtractLine[]
  invoiceId?: string
  linking?: ExtractsLinking
}) {
  const notice = linking?.state.notice ?? null
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
          const followable =
            linking != null &&
            invoiceId != null &&
            line.is_section_total &&
            findSectionBreakdown(linking.extracts, invoiceId, line.id) != null
          const gap =
            notice != null && notice.invoiceLineId === line.id ? notice.gap : null
          return (
            <Fragment key={line.id}>
              <TableRow
                id={linkRowIds.invoiceLine(line.id)}
                tabIndex={-1}
                className="scroll-mt-24 focus:outline-none"
              >
                <TableCell className="text-muted-foreground">
                  {line.sequence_no}
                </TableCell>
                <TableCell>
                  <span className="inline-flex items-center gap-2">
                    {followable ? (
                      <button
                        type="button"
                        onClick={() => linking.onSectionTotal(invoiceId, line.id)}
                        aria-label={`Show the engineer assessment operations in ${lineItemTypeLabel(line.line_item_type)}`}
                        className="font-medium underline decoration-dotted underline-offset-4 hover:decoration-solid"
                      >
                        {lineItemTypeLabel(line.line_item_type)}
                      </button>
                    ) : (
                      lineItemTypeLabel(line.line_item_type)
                    )}
                    {line.is_section_total ? <SectionTotalBadge /> : null}
                  </span>
                </TableCell>
                <TableCell>
                  {followable ? (
                    <button
                      type="button"
                      onClick={() => linking.onSectionTotal(invoiceId, line.id)}
                      aria-label={`Show the engineer assessment operations behind ${line.description}`}
                      className="text-left font-medium underline decoration-dotted underline-offset-4 hover:decoration-solid"
                    >
                      {line.description}
                    </button>
                  ) : (
                    line.description
                  )}
                </TableCell>
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
              {gap != null && linking ? (
                <TableRow>
                  <TableCell colSpan={6} className="whitespace-normal">
                    <div
                      role="status"
                      className="max-w-2xl space-y-3 rounded-md border border-dashed bg-background p-3"
                    >
                      <div>
                        <p className="text-sm font-medium">
                          {LINK_GAP_MESSAGES[gap].title}
                        </p>
                        <p className="mt-1 text-sm text-muted-foreground">
                          {LINK_GAP_MESSAGES[gap].body}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={linking.onDismissNotice}
                        className="rounded-md border px-2.5 py-1 text-sm font-medium text-muted-foreground hover:text-foreground"
                      >
                        Dismiss
                      </button>
                    </div>
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
  const collapse = (key: string) =>
    setChoices((previous) => new Map(previous).set(key, false))
  return { isExpanded, toggle, collapse }
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
  linking,
}: {
  invoices: InvoiceExtractPayload[]
  /** `all` opens every invoice (tests have no pointer to click a toggle);
   * `auto` and `none` both open nothing. */
  expansion?: ExtractsExpansion
  linking?: ExtractsLinking
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
          const partner: Partner = linking
            ? invoicePartner(linking.extracts, invoice)
            : {
                paired: invoice.paired_assessment_number != null,
                number: invoice.paired_assessment_number,
                id: null,
                onScreen: false,
              }
          const focused = linking?.state.focusedInvoiceId === key
          return (
            <Fragment key={key}>
              <TableRow
                id={linkRowIds.invoice(key)}
                tabIndex={-1}
                data-state={focused ? "selected" : undefined}
                className="scroll-mt-24 focus:outline-none"
              >
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
                  <AssociationCell
                    partner={partner}
                    documentLabel="engineer assessment"
                    onFollow={
                      linking ? () => linking.onAssessmentNumber(key) : undefined
                    }
                  />
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
                      <InvoiceLinesTable
                        lines={invoice.lines}
                        invoiceId={key}
                        linking={linking}
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
  linking,
}: {
  assessments: AssessmentExtractPayload[]
  /** There is no auto-expand rule on this side -- a row opens when a link
   * from the invoice table lands on it, and a 120-operation report would push everything else off
   * the page -- so `auto` and `none` are the same thing here. */
  expansion?: ExtractsExpansion
  /** With `linking`, the row a jump from the invoice table lands on is held
   * open -- filtered to the clicked section when there is one -- until the
   * reader collapses it or follows another link. */
  linking?: ExtractsLinking
}) {
  const { isExpanded, toggle, collapse } = useRowExpansion(expansion === "all")
  const link = linking?.state.link ?? null
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
          const linked = link != null && link.assessmentId === key ? link : null
          const expanded = linked != null || isExpanded(key)
          const detailId = `assessment-extract-detail-${key}`
          const partner: Partner = linking
            ? assessmentPartner(linking.extracts, assessment)
            : {
                paired: assessment.pair_status === "paired",
                number: assessment.paired_invoice_number,
                id: null,
                onScreen: false,
              }
          const shownLines = linked?.breakdown
            ? filterSectionOperations(assessment.lines, linked.breakdown)
            : assessment.lines
          return (
            <Fragment key={key}>
              <TableRow
                id={linkRowIds.assessment(key)}
                tabIndex={-1}
                data-state={linked ? "selected" : undefined}
                className="scroll-mt-24 focus:outline-none"
              >
                <TableCell>
                  <ExpandToggleButton
                    expanded={expanded}
                    onToggle={() => {
                      if (linked && linking) {
                        collapse(key)
                        linking.onRelease()
                      } else {
                        toggle(key)
                      }
                    }}
                    label={`lines for engineer assessment ${assessment.assessment_number ?? key}`}
                    controls={detailId}
                  />
                </TableCell>
                <TableCell className="font-medium">
                  {assessment.assessment_number ?? "—"}
                </TableCell>
                <TableCell>
                  <AssociationCell
                    partner={partner}
                    documentLabel="invoice"
                    onFollow={
                      linking ? () => linking.onInvoiceNumber(key) : undefined
                    }
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
                    {linked && linking ? (
                      <LinkBanner
                        link={linked}
                        invoiceNumber={
                          linking.extracts.invoice_extracts.find(
                            (invoice) => invoice.invoice_id === linked.invoiceId
                          )?.invoice_number ?? null
                        }
                        shown={shownLines.length}
                        total={assessment.lines.length}
                        onShowAll={linking.onShowAll}
                        onBack={linking.onBack}
                      />
                    ) : null}
                    {shownLines.length > 0 ? (
                      <AssessmentLinesTable lines={shownLines} />
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
  const [linkState, setLinkState] = useState<ExtractsLinkState>(NO_LINK)
  const scopeSentence = scopeLabel ? ` Showing ${scopeLabel} only.` : null

  // Bring the jump's target into view once it has rendered. `inline: "start"`
  // matters as much as the vertical scroll: both tables are wider than the
  // screen, and a reader scrolled right in one table would otherwise land on
  // the far end of the target row. `scrollIntoView` scrolls every scrolling
  // ancestor, the tables' own overflow containers included.
  const scroll = linkState.scroll
  useEffect(() => {
    if (scroll == null) return
    const target = scroll.elementIds
      .map((id) => document.getElementById(id))
      .find((element) => element != null)
    if (!target) return
    target.scrollIntoView({ behavior: "smooth", block: "start", inline: "start" })
    target.focus({ preventScroll: true })
  }, [scroll])
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

  const linking: ExtractsLinking = {
    extracts,
    state: linkState,
    onSectionTotal: (invoiceId, invoiceLineId) =>
      setLinkState((state) =>
        followSectionTotal(state, extracts, invoiceId, invoiceLineId)
      ),
    onAssessmentNumber: (invoiceId) =>
      setLinkState((state) => followAssessmentNumber(state, extracts, invoiceId)),
    onInvoiceNumber: (assessmentId) =>
      setLinkState((state) => followInvoiceNumber(state, extracts, assessmentId)),
    onShowAll: () => setLinkState(showAllOperations),
    onBack: () => setLinkState(backToInvoice),
    onRelease: () => setLinkState(releaseLink),
    onDismissNotice: () => setLinkState(dismissNotice),
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
                screen exists to evidence. `section_breakdowns` is not
                rendered here as a split; it is read only to link the two
                tables (see `extracts-link.ts`). */}
            <div>
              <h3 className="text-sm font-semibold">
                Invoice extracts and associated engineer assessment
              </h3>
              <div className="mt-2 overflow-x-auto rounded-lg border">
                <InvoiceExtractsTable
                  invoices={extracts.invoice_extracts}
                  linking={linking}
                />
              </div>
            </div>
            <div>
              <h3 className="text-sm font-semibold">
                Engineer assessment extracts and invoice association
              </h3>
              <div className="mt-2 overflow-x-auto rounded-lg border">
                <AssessmentExtractsTable
                  assessments={extracts.assessment_extracts}
                  linking={linking}
                />
              </div>
            </div>
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}
