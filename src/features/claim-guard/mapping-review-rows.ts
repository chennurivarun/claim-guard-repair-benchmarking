import type {
  CaseMappingPayload,
  IntakeGroup,
  MappingAssessmentRow,
  MappingInvoiceOption,
} from "./document-api"
import { summarisePairKeyVerdicts } from "./pair-verdicts"

/** The pure row logic behind the mapping review screen: how an invoice is
 * named, what a row's identity reads as, which rows come first, and the one
 * sentence of evidence beside each pairing.
 *
 * Separate from `screens-document-mapping.tsx` so it can be asserted without
 * rendering, and because the project's fast-refresh lint rule keeps a
 * component file to components.
 */

/** Who the app records a mapping decision against. The same standing handler
 * identity the rest of the pilot writes into its audit events. */
export const MAPPING_ACTOR = "pilot.handler"

const NOT_PRINTED = "Not printed"

/** How one invoice is named in the picker and on the row.
 *
 * Never a bare row number: a folder hand-over gives several invoices the same
 * blank invoice number, and "Invoice 3" would be an accident of alphabetical
 * order rather than anything printed on the paper. The filename is the
 * fallback because it is the one thing the handler chose. */
export function invoiceLabel(invoice: MappingInvoiceOption): string {
  const printed = invoice.invoice_number?.trim()
  const name = printed || invoice.document_filename || invoice.invoice_id
  const registration = invoice.registration?.trim()
  return registration ? `${name} · ${registration}` : name
}

/** The assessment's own identity, as the documents print it. */
export function assessmentIdentity(row: MappingAssessmentRow): string[] {
  return [
    `Assessment ${row.assessment_number?.trim() || NOT_PRINTED}`,
    `Registration ${row.registration?.trim() || NOT_PRINTED}`,
    `Claim ${row.claim_reference?.trim() || NOT_PRINTED}`,
    `Policy ${row.policy_number?.trim() || NOT_PRINTED}`,
  ]
}

/** Unpaired assessments first, then handler-made links, then the rest.
 *
 * The unpaired rows are the point of this screen -- they are the documents
 * the pairing rule refused to guess at and that nothing else in the product
 * can rescue -- so they are never allowed to sit below a page of links that
 * need no attention. A handler link comes next because it is the other thing
 * a reviewer of this screen is looking for. Order within a group is the
 * order the payload arrived in, which is oldest document first. */
export function sortMappingRows(
  rows: MappingAssessmentRow[]
): MappingAssessmentRow[] {
  const rank = (row: MappingAssessmentRow) =>
    row.pair_status !== "paired" ? 0 : row.pair_source === "manual" ? 1 : 2
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => rank(a.row) - rank(b.row) || a.index - b.index)
    .map((entry) => entry.row)
}

/** The one-line evidence sentence beside a pairing.
 *
 * Deliberately not a percentage. `pair_confidence` is matched keys over
 * *compared* keys, so every automatic pair scores 1.0 by construction and
 * "100%" would say nothing; and a handler's link carries no confidence at all
 * because confidence is a property of the rule, not of a person's judgement.
 * `summarisePairKeyVerdicts` already renders the denominator form. */
export function pairEvidence(row: MappingAssessmentRow): string {
  if (row.pair_source === "manual" && row.pair_status === "paired") {
    const summary = summarisePairKeyVerdicts(row.pair_key_verdicts)
    const by = row.manual_override?.actor
      ? `Linked by hand by ${row.manual_override.actor}`
      : "Linked by hand"
    return summary.headline ? `${by} · ${summary.headline}` : by
  }
  if (row.pair_status === "paired") {
    const summary = summarisePairKeyVerdicts(row.pair_key_verdicts)
    return summary.headline ?? row.pair_reasons.join(" · ")
  }
  return row.pair_reasons.join(" · ") || "Not paired"
}

/** One source's slice of the mapping, with its counts recomputed.
 *
 * The screen asks the server for one intake group, but the per-assessment
 * override endpoint answers with the mapping it holds, and a third-party
 * screen must never show -- or count -- an In-house row. So the rows are
 * filtered here as well. A row with no `intake_group` is kept: the server
 * was asked for this group, so an untagged row is its answer. */
export function scopeMapping(
  payload: CaseMappingPayload,
  intakeGroup: IntakeGroup | undefined
): CaseMappingPayload {
  if (!intakeGroup) return payload
  const ours = (group: IntakeGroup | null) =>
    group == null || group === intakeGroup
  const assessments = payload.assessments.filter((row) => ours(row.intake_group))
  const paired = assessments.filter((row) => row.pair_status === "paired")
  return {
    ...payload,
    invoices: payload.invoices.filter((invoice) => ours(invoice.intake_group)),
    assessments,
    assessments_total: assessments.length,
    paired: paired.length,
    unpaired: assessments.length - paired.length,
    manual: paired.filter((row) => row.pair_source === "manual").length,
  }
}
