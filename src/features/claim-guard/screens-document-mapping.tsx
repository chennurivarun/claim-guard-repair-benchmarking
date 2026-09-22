import { useCallback, useEffect, useState } from "react"
import { LinkIcon, UserCheckIcon } from "lucide-react"

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

import {
  approveCaseMapping,
  documentApiErrorMessage,
  fetchCaseMapping,
  overrideAssessmentMapping,
  type CaseMappingPayload,
  type IntakeGroup,
  type MappingAssessmentRow,
  type MappingInvoiceOption,
} from "./document-api"
import {
  MAPPING_ACTOR,
  assessmentIdentity,
  invoiceLabel,
  pairEvidence,
  scopeMapping,
  sortMappingRows,
} from "./mapping-review-rows"
import { ScreenHeading } from "./shared"

function StatusPill({ row }: { row: MappingAssessmentRow }) {
  if (row.pair_status !== "paired")
    return <Badge variant="warning">Not paired</Badge>
  if (row.pair_source === "manual")
    return (
      <Badge variant="outline" className="gap-1">
        <UserCheckIcon className="size-3" aria-hidden />
        Linked by hand
      </Badge>
    )
  return (
    <Badge variant="success" className="gap-1">
      <LinkIcon className="size-3" aria-hidden />
      Paired automatically
    </Badge>
  )
}

function AssessmentCard({
  row,
  invoices,
  disabled,
  busy,
  onChange,
}: {
  row: MappingAssessmentRow
  invoices: MappingInvoiceOption[]
  disabled: boolean
  busy: boolean
  onChange: (invoiceId: string | null) => void
}) {
  // The select is the whole control: choosing an invoice links, choosing the
  // blank option unlinks. A separate "clear" button would be a second way to
  // say the same thing.
  const value = row.paired_invoice_id ?? ""
  const stale =
    row.manual_override?.state === "linked" && !row.manual_override.applied
  return (
    <Card data-testid="mapping-assessment">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-base">
              {row.document_filename || row.assessment_id}
            </CardTitle>
            <CardDescription>
              {assessmentIdentity(row).join(" · ")}
            </CardDescription>
          </div>
          <StatusPill row={row} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">{pairEvidence(row)}</p>
        {stale && (
          <p className="text-sm text-amber-700 dark:text-amber-300">
            The invoice you chose for this engineer assessment is no longer
            available in this claim, so the automatic proposal is shown
            instead. Choose again.
          </p>
        )}
        <label className="block space-y-2 text-sm font-medium">
          <span>Paired repair invoice</span>
          <select
            className="h-9 w-full min-w-56 rounded-md border bg-background px-3 text-sm"
            aria-label={`Paired repair invoice for ${
              row.assessment_number || row.document_filename || "this engineer assessment"
            }`}
            disabled={disabled || busy}
            value={value}
            onChange={(event) => onChange(event.target.value || null)}
          >
            <option value="">No invoice — leave this assessment unpaired</option>
            {invoices.map((invoice) => (
              <option key={invoice.invoice_id} value={invoice.invoice_id}>
                {invoiceLabel(invoice)}
              </option>
            ))}
          </select>
        </label>
        {row.manual_override && (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs text-muted-foreground">
              {row.manual_override.state === "cleared"
                ? "A handler unlinked this engineer assessment."
                : "A handler chose this invoice."}
              {row.manual_override.at
                ? ` ${new Date(row.manual_override.at).toLocaleString()}.`
                : ""}
            </p>
            <Button
              variant="ghost"
              size="sm"
              disabled={disabled || busy}
              onClick={() => onChange("__reset__")}
            >
              Use the automatic pairing
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/** The mapping review step: which repair invoice each engineer assessment
 * belongs to, and the handler's approval of that.
 *
 * It exists because the pairing engine deliberately refuses to guess. Two
 * assessments that fit one invoice equally well leave it unlinked; conflicting
 * printed identities refuse the pair. Every one of those refusals reads
 * "manual linkage required", and until this screen there was no way to
 * perform that linkage, so the documents stayed stuck for good.
 *
 * It replaces the standing "Re-run pairing sweep" button. The sweep still
 * runs -- it is what Approve does -- but re-running it is no longer offered
 * as a substitute for a person correcting the mapping.
 *
 * With `intakeGroup` it is one source's mapping -- read, shown and approved
 * for that group alone -- which is how each source's Document intelligence
 * mounts it. Without it, the whole claim, as under Advanced tools. */
export function DocumentMappingScreen({
  caseReference,
  finalised,
  intakeGroup,
  onApproved,
  onApprovalChange,
  onContinue,
}: {
  caseReference: string
  finalised: boolean
  intakeGroup?: IntakeGroup
  onApproved?: () => Promise<void> | void
  /** Told whenever the approval state read from the server changes, so a
   * parent can put the extract tables after approval. */
  onApprovalChange?: (approved: boolean) => void
  /** Omitted when the extracts follow on the same screen. */
  onContinue?: () => void
}) {
  const [rawMapping, setMapping] = useState<CaseMappingPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingId, setSavingId] = useState<string | null>(null)
  const [approving, setApproving] = useState(false)
  const mapping = rawMapping ? scopeMapping(rawMapping, intakeGroup) : null

  const load = useCallback(async () => {
    try {
      setMapping(await fetchCaseMapping(caseReference, intakeGroup))
      setError(null)
    } catch (e) {
      setMapping(null)
      setError(documentApiErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [caseReference, intakeGroup])

  useEffect(() => {
    let active = true
    void fetchCaseMapping(caseReference, intakeGroup)
      .then((payload) => {
        if (!active) return
        setMapping(payload)
        setError(null)
      })
      .catch((e) => {
        if (!active) return
        setMapping(null)
        setError(documentApiErrorMessage(e))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [caseReference, intakeGroup])

  async function change(assessmentId: string, invoiceId: string | null) {
    if (savingId || approving || finalised) return
    setSavingId(assessmentId)
    setError(null)
    try {
      setMapping(
        await overrideAssessmentMapping(caseReference, assessmentId, {
          actor: MAPPING_ACTOR,
          decision:
            invoiceId === "__reset__"
              ? "reset"
              : invoiceId
                ? "link"
                : "unlink",
          invoiceId,
        })
      )
      // The override endpoint is not scoped: its answer carries the whole
      // claim's approval, not this group's. Re-read the group so the
      // approval banner speaks for this source only.
      if (intakeGroup) await load()
    } catch (e) {
      setError(documentApiErrorMessage(e))
      // The server refused, so the row on screen may no longer match the
      // row in the database. Re-read rather than leave the select showing a
      // choice that was not accepted.
      await load()
    } finally {
      setSavingId(null)
    }
  }

  async function approve() {
    if (savingId || approving || finalised) return
    setApproving(true)
    setError(null)
    try {
      setMapping(
        await approveCaseMapping(caseReference, MAPPING_ACTOR, intakeGroup)
      )
      await onApproved?.()
    } catch (e) {
      setError(documentApiErrorMessage(e))
    } finally {
      setApproving(false)
    }
  }

  const rows = sortMappingRows(mapping?.assessments ?? [])
  const approved = mapping?.approval.approved ?? false
  const manualReviewInvoices = (mapping?.invoices ?? []).filter(
    (invoice) => invoice.unmapped_assessment
  )

  useEffect(() => {
    onApprovalChange?.(approved)
  }, [approved, onApprovalChange])

  return (
    <>
      <ScreenHeading
        title="Mapping review"
        description="Check which repair invoice each engineer assessment belongs to, change any pairing by hand, then approve. Approving reads the documents against the pairs you confirmed."
        action={
          <>
            <Button
              disabled={loading || approving || !!savingId || finalised || !mapping}
              onClick={() => void approve()}
            >
              {approving
                ? "Approving mapping…"
                : approved
                  ? "Re-approve mapping"
                  : "Approve mapping"}
            </Button>
            {onContinue ? (
              <Button
                variant="outline"
                disabled={!approved}
                onClick={onContinue}
              >
                View extracts
              </Button>
            ) : null}
          </>
        }
      />

      {error && (
        <Alert variant="destructive">
          <AlertTitle>The mapping could not be changed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {finalised && (
        <Alert>
          <AlertTitle>Finalised case</AlertTitle>
          <AlertDescription>
            Create a new case revision to change the mapping.
          </AlertDescription>
        </Alert>
      )}

      {approved ? (
        <Alert>
          <AlertTitle>Mapping approved</AlertTitle>
          <AlertDescription>
            {mapping?.approval.approved_by
              ? `Approved by ${mapping.approval.approved_by}. `
              : ""}
            The documents are being read against the pairs you confirmed, and
            the extract tables follow. Changing a pairing, or uploading another
            document, reopens this step for approval again.
          </AlertDescription>
        </Alert>
      ) : (
        <Alert>
          <AlertTitle>Mapping not approved yet</AlertTitle>
          <AlertDescription>
            The pairing engine proposes; you decide. Inspect the extracted
            documents and matching reasons before approving these pairs.
          </AlertDescription>
        </Alert>
      )}

      {manualReviewInvoices.length ? (
        <Alert variant="destructive">
          <AlertTitle>Invoices needing manual review</AlertTitle>
          <AlertDescription>
            {manualReviewInvoices
              .map(
                (invoice) =>
                  invoice.invoice_number || invoice.document_filename || invoice.invoice_id
              )
              .join(", ")}
            {" "}
            have no confirmed engineer-assessment mapping. Resolve the pairing
            or leave the invoice in manual review.
          </AlertDescription>
        </Alert>
      ) : null}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading the mapping…</p>
      ) : !mapping ? null : !rows.length ? (
        <Card>
          <CardHeader>
            <CardTitle>No engineer assessments yet</CardTitle>
            <CardDescription>
              No assessment records were extracted in this source. Add the reports
              using the Engineer assessments picker on Upload documents. You can
              upload assessments separately after the invoices. If already
              uploaded, check their processing status and source.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            {mapping.assessments_total} engineer{" "}
            {mapping.assessments_total === 1 ? "assessment" : "assessments"} ·{" "}
            {mapping.unpaired} awaiting a pairing decision · {mapping.manual}{" "}
            linked by hand
          </p>
          <div className="grid gap-4">
            {rows.map((row) => (
              <AssessmentCard
                key={row.assessment_id}
                row={row}
                invoices={mapping.invoices}
                disabled={finalised}
                busy={savingId === row.assessment_id || approving}
                onChange={(invoiceId) => void change(row.assessment_id, invoiceId)}
              />
            ))}
          </div>
        </>
      )}
    </>
  )
}
