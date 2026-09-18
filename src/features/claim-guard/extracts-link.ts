/** The link between the two extracts tables on Document intelligence.
 *
 * On 17 Sep the client split the screen into two tables that each show only
 * what their own document prints: an invoice that rolls its parts up into
 * "Total Parts £448.91" shows that one line, and the parts behind it sit on
 * the engineer assessment in the table below. What was missing was a way to
 * get from one to the other -- "when you click on that specific invoice and
 * Total Parts, it should go down to the table below and show all those
 * parts."
 *
 * Everything here is pure: the table components turn a click into one of
 * these transitions and the section scrolls to whatever `scroll` names.
 *
 * **Which operations sit behind a section.** The frontend does not carry its
 * own section -> category rule. The backend's `_section_categories`
 * (`backend/app/services/engineer_assessment.py`) decides it -- a section
 * maps to operations of its own code, except an invoice's Total Labour,
 * which pays for both labour *and* paintwork -- and it publishes the result
 * as the `rows` of each `section_breakdowns` entry. The filter takes the
 * categories those rows carry and keeps the engineer assessment's operations
 * in them. Because the backend's rows are *every* operation in the section's
 * categories, that is exactly the same set of operations, and a change to
 * the backend rule reaches this screen without a frontend change.
 *
 * **Who is paired to whom.** The extracts payload carries the partner's
 * *number* on each row but not its id, and a number can be missing (format
 * 1's invoice prints none) or shared (formats 1 and 7 print the same one).
 * The id comes from `section_breakdowns`, which holds `invoice_id` and
 * `assessment_id` side by side; only when an invoice prints no section total
 * does this fall back to both rows naming each other's number, and then only
 * when exactly one row on the screen does.
 */
import type {
  AssessmentExtractLine,
  AssessmentExtractPayload,
  ClaimExtractsPayload,
  InvoiceExtractPayload,
  SectionBreakdownPayload,
} from "@/lib/api"

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

function toNumber(value: string | number | null | undefined) {
  if (value == null || value === "") return null
  const parsed = typeof value === "number" ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
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
export type BreakdownGap =
  | "unpaired"
  | "unresolved"
  | "no-section-total"
  | "total-only"

export function breakdownGap(
  breakdown: SectionBreakdownPayload
): BreakdownGap | null {
  if (hasBreakdownRows(breakdown)) return null
  if (breakdown.assessment_id == null) return "unpaired"
  if (!RESOLVABLE_SECTION_TYPES.has(breakdown.line_item_type)) return "unresolved"
  if (toNumber(breakdown.assessment_total) == null) return "no-section-total"
  return "total-only"
}

/** Why a click did not jump: one of the four breakdown gaps, or -- on a
 * screen scoped to one source -- the paired engineer assessment exists but
 * was uploaded under another source, so this screen has no row for it. */
export type LinkGap = BreakdownGap | "off-screen"

export interface AssessmentLink {
  assessmentId: string
  invoiceId: string
  /** The invoice line the reader clicked, so Back returns to it. Null when
   * the jump came from the association column. */
  invoiceLineId: string | null
  /** The section the operations are filtered to; null shows them all. */
  breakdown: SectionBreakdownPayload | null
}

export interface ExtractsLinkState {
  link: AssessmentLink | null
  notice: { invoiceLineId: string; gap: LinkGap } | null
  focusedInvoiceId: string | null
  /** Element ids to bring into view, the first one present wins. `seq`
   * changes on every jump so a repeat click scrolls again. */
  scroll: { elementIds: string[]; seq: number } | null
}

export const NO_LINK: ExtractsLinkState = {
  link: null,
  notice: null,
  focusedInvoiceId: null,
  scroll: null,
}

export const linkRowIds = {
  assessment: (assessmentId: string) => `assessment-extract-row-${assessmentId}`,
  invoice: (invoiceId: string) => `invoice-extract-row-${invoiceId}`,
  invoiceLine: (lineId: string) => `invoice-extract-line-${lineId}`,
}

function scrollTo(state: ExtractsLinkState, ...elementIds: string[]) {
  return { elementIds, seq: (state.scroll?.seq ?? 0) + 1 }
}

export function findSectionBreakdown(
  extracts: ClaimExtractsPayload,
  invoiceId: string,
  invoiceLineId: string
) {
  return (
    extracts.section_breakdowns.find(
      (breakdown) =>
        breakdown.invoice_id === invoiceId &&
        breakdown.invoice_line_item_id === invoiceLineId
    ) ?? null
  )
}

/** The engineer assessment operations behind one section total: those in a
 * category the backend put in the section's rows (see the module note). */
export function filterSectionOperations(
  lines: AssessmentExtractLine[],
  breakdown: SectionBreakdownPayload
) {
  const categories = new Set(breakdown.rows.map((row) => row.category))
  return lines.filter(
    (line) => line.line_item_type != null && categories.has(line.line_item_type)
  )
}

/** The other document of a pair, as one row of the table sees it. `paired`
 * and `number` are separate facts: a paired row whose partner printed no
 * number is still paired. `onScreen` is false when the partner is known but
 * not on this (scoped) screen. */
export interface Partner {
  paired: boolean
  number: string | null
  id: string | null
  onScreen: boolean
}

function uniqueId(ids: string[]) {
  return ids.length === 1 ? ids[0] : null
}

export function invoicePartner(
  extracts: ClaimExtractsPayload,
  invoice: InvoiceExtractPayload
): Partner {
  const fromBreakdown =
    extracts.section_breakdowns.find(
      (breakdown) =>
        breakdown.invoice_id === invoice.invoice_id &&
        breakdown.assessment_id != null
    )?.assessment_id ?? null
  const id =
    fromBreakdown ??
    (invoice.paired_assessment_number == null || invoice.invoice_number == null
      ? null
      : uniqueId(
          extracts.assessment_extracts
            .filter(
              (assessment) =>
                assessment.pair_status === "paired" &&
                assessment.assessment_number === invoice.paired_assessment_number &&
                assessment.paired_invoice_number === invoice.invoice_number
            )
            .map((assessment) => assessment.assessment_id)
        ))
  return {
    paired: id != null || invoice.paired_assessment_number != null,
    number: invoice.paired_assessment_number,
    id,
    onScreen:
      id != null &&
      extracts.assessment_extracts.some(
        (assessment) => assessment.assessment_id === id
      ),
  }
}

export function assessmentPartner(
  extracts: ClaimExtractsPayload,
  assessment: AssessmentExtractPayload
): Partner {
  const paired = assessment.pair_status === "paired"
  const fromBreakdown =
    extracts.section_breakdowns.find(
      (breakdown) => breakdown.assessment_id === assessment.assessment_id
    )?.invoice_id ?? null
  const id = !paired
    ? null
    : (fromBreakdown ??
      (assessment.paired_invoice_number == null ||
      assessment.assessment_number == null
        ? null
        : uniqueId(
            extracts.invoice_extracts
              .filter(
                (invoice) =>
                  invoice.invoice_number === assessment.paired_invoice_number &&
                  invoice.paired_assessment_number === assessment.assessment_number
              )
              .map((invoice) => invoice.invoice_id)
          )))
  return {
    paired,
    number: assessment.paired_invoice_number,
    id,
    onScreen:
      id != null &&
      extracts.invoice_extracts.some((invoice) => invoice.invoice_id === id),
  }
}

/** A rolled-up total was clicked: jump to its engineer assessment filtered
 * to that section, or -- when there is nothing to jump to -- leave the page
 * where it is and say why under the line that was clicked. */
export function followSectionTotal(
  state: ExtractsLinkState,
  extracts: ClaimExtractsPayload,
  invoiceId: string,
  invoiceLineId: string
): ExtractsLinkState {
  const breakdown = findSectionBreakdown(extracts, invoiceId, invoiceLineId)
  if (breakdown == null) return state
  const assessmentId = breakdown.assessment_id
  const onScreen =
    assessmentId != null &&
    extracts.assessment_extracts.some(
      (assessment) => assessment.assessment_id === assessmentId
    )
  const gap = breakdownGap(breakdown) ?? (onScreen ? null : "off-screen")
  if (gap != null || assessmentId == null) {
    return { ...state, notice: { invoiceLineId, gap: gap ?? "unpaired" } }
  }
  return {
    link: { assessmentId, invoiceId, invoiceLineId, breakdown },
    notice: null,
    focusedInvoiceId: null,
    scroll: scrollTo(state, linkRowIds.assessment(assessmentId)),
  }
}

/** The associated engineer assessment number was clicked: the same jump,
 * unfiltered. Not offered for a partner that is not on this screen. */
export function followAssessmentNumber(
  state: ExtractsLinkState,
  extracts: ClaimExtractsPayload,
  invoiceId: string
): ExtractsLinkState {
  const invoice = extracts.invoice_extracts.find(
    (candidate) => candidate.invoice_id === invoiceId
  )
  if (!invoice) return state
  const partner = invoicePartner(extracts, invoice)
  if (partner.id == null || !partner.onScreen) return state
  return {
    link: {
      assessmentId: partner.id,
      invoiceId,
      invoiceLineId: null,
      breakdown: null,
    },
    notice: null,
    focusedInvoiceId: null,
    scroll: scrollTo(state, linkRowIds.assessment(partner.id)),
  }
}

/** The associated invoice number was clicked: jump up to that invoice. */
export function followInvoiceNumber(
  state: ExtractsLinkState,
  extracts: ClaimExtractsPayload,
  assessmentId: string
): ExtractsLinkState {
  const assessment = extracts.assessment_extracts.find(
    (candidate) => candidate.assessment_id === assessmentId
  )
  if (!assessment) return state
  const partner = assessmentPartner(extracts, assessment)
  if (partner.id == null || !partner.onScreen) return state
  return {
    ...state,
    notice: null,
    focusedInvoiceId: partner.id,
    scroll: scrollTo(state, linkRowIds.invoice(partner.id)),
  }
}

export function showAllOperations(state: ExtractsLinkState): ExtractsLinkState {
  if (state.link == null) return state
  return {
    ...state,
    link: { ...state.link, breakdown: null },
    scroll: scrollTo(state, linkRowIds.assessment(state.link.assessmentId)),
  }
}

/** Back up to where the reader came from: the invoice line they clicked if
 * its row is still open, otherwise the invoice row itself. The link stays,
 * so the filtered engineer assessment is still there to come back down to. */
export function backToInvoice(state: ExtractsLinkState): ExtractsLinkState {
  if (state.link == null) return state
  const { invoiceId, invoiceLineId } = state.link
  return {
    ...state,
    focusedInvoiceId: invoiceId,
    scroll: scrollTo(
      state,
      ...(invoiceLineId ? [linkRowIds.invoiceLine(invoiceLineId)] : []),
      linkRowIds.invoice(invoiceId)
    ),
  }
}

export function releaseLink(state: ExtractsLinkState): ExtractsLinkState {
  return { ...state, link: null }
}

export function dismissNotice(state: ExtractsLinkState): ExtractsLinkState {
  return { ...state, notice: null }
}
