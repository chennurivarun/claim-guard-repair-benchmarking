import { useEffect, useState, type InputHTMLAttributes } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  fetchClaimExtracts,
  fetchClaimInvoices,
  getApiErrorMessage,
  type ClaimExtractsPayload,
  type ClaimInvoiceSummary,
} from "@/lib/api"
import {
  fetchCaseDocuments,
  processUploadedDocument,
  retryEmptyDocument,
  runCaseLinkSweep,
  uploadCurrentDocument,
  type IntakeGroup,
  type UploadedDocument,
} from "./document-api"
import { ExtractsSection } from "./extracts-section"
import { runIntakeBatch, type IntakeBatchEntry } from "./intake-batch"
import { SourceIntelligenceScreen } from "./screens-source-intelligence"
import { ScreenHeading, StatusBadge } from "./shared"
import { INTAKE_GROUP_LABELS, intakeGroupsFor } from "./source-scope"

// The two reference buckets carry the names Neha uses for them (D1 of the
// 18 Sep spec: relabel, don't duplicate). The live bucket keeps its picker
// label -- "New invoice" is the heading, "New repair invoices" the files.
const labels: Record<IntakeGroup, string> = {
  historical_claim: INTAKE_GROUP_LABELS.historical_claim,
  in_house: INTAKE_GROUP_LABELS.in_house,
  live: "New repair invoices",
}
const accept = ".pdf,.doc,.docx"

/** `webkitdirectory` turns a file input into a folder picker in every browser
 * that ships Chromium or WebKit; React has no typing for it, so it is spread
 * in as a plain attribute. Same shape as the picker in
 * `screens-document-workflow.tsx`. */
const directoryInputProps = {
  webkitdirectory: "",
  directory: "",
} as InputHTMLAttributes<HTMLInputElement>

/** A folder picker hands back everything in the folder -- .DS_Store, stray
 * spreadsheets, the lot -- so the selection is filtered to what intake can
 * actually read rather than failing file by file on the server. */
function isSupportedDocument(file: File) {
  const name = file.name.toLowerCase()
  return [".pdf", ".doc", ".docx"].some((extension) => name.endsWith(extension))
}

/** The upload and batch flow. Unscoped, it is the two Advanced tools screens
 * it always was (Benchmark data setup, whole-claim Document Intelligence).
 * With `scope`, it is one source's "Upload documents": one bucket, repair
 * invoices and engineer assessments side by side, files or a folder on
 * both, and nothing else -- the extracts belong to that source's Document
 * intelligence, which `onProcessed` / `onContinue` lead to. */
export function ClientIntakeScreen({
  caseReference,
  setup,
  scope,
  finalised,
  onProcessed,
  onContinue,
  onOpenBenchmarks,
  onOpenManualReview,
}: {
  caseReference: string
  setup: boolean
  scope?: IntakeGroup
  finalised: boolean
  onProcessed: (documentId?: string) => Promise<void>
  onContinue: () => void
  onOpenBenchmarks?: () => void
  onOpenManualReview: (documentId: string) => void
}) {
  const [documents, setDocuments] = useState<UploadedDocument[]>([])
  const [invoices, setInvoices] = useState<ClaimInvoiceSummary[]>([])
  const [files, setFiles] = useState<Partial<Record<IntakeGroup, File[]>>>({})
  const [estimates, setEstimates] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  /** The per-file failure summary lives in its own state, not in `error`.
   * It used to be written into `error` and then immediately overwritten by
   * the outer catch if the refresh that followed threw, so the one message
   * naming which files failed was the easiest thing on the screen to lose. */
  const [fileFailures, setFileFailures] = useState<string[]>([])
  const [sweepNotice, setSweepNotice] = useState<string | null>(null)
  const [results, setResults] = useState<
    Array<{ name: string; role: string; status: string }>
  >([])
  /** Bumped after every batch so the file inputs drop their DOM selection:
   * without it, re-picking the same folder fires no `change` event. */
  const [pickerKey, setPickerKey] = useState(0)
  const [receiptVersion, setReceiptVersion] = useState(0)
  /** Only the unscoped live screen carries the extract tables; a scoped
   * upload leaves them to its own Document intelligence. */
  const showsExtracts = !setup && !scope
  const [extracts, setExtracts] = useState<ClaimExtractsPayload | null>(null)
  const [extractsLoading, setExtractsLoading] = useState(showsExtracts)
  const [extractsError, setExtractsError] = useState<string | null>(null)
  const groups = intakeGroupsFor({ setup, scope })
  /** Every intake bucket accepts its engineer assessments beside its
   * invoices. The benchmark setup screen used to hide the assessment picker
   * for the two reference buckets, which meant those invoices could never be
   * paired and their identity fields stayed "Not extracted" until someone
   * uploaded the same files through a different screen. */
  const takesAssessments = (group: IntakeGroup) =>
    group === "live" || group === "historical_claim" || group === "in_house"

  /** The extracts endpoint is case-scoped, so it only means something on the
   * live screen; see the `showsExtracts` guard on the section itself. */
  async function loadExtracts() {
    if (!showsExtracts) return
    try {
      setExtracts(await fetchClaimExtracts(caseReference))
      setExtractsError(null)
    } catch (e) {
      setExtracts(null)
      setExtractsError(getApiErrorMessage(e))
    } finally {
      setExtractsLoading(false)
    }
  }

  async function refresh() {
    const [docs, rows] = await Promise.all([
      fetchCaseDocuments(caseReference),
      fetchClaimInvoices(caseReference),
    ])
    setDocuments(docs)
    setInvoices(rows)
    setReceiptVersion((version) => version + 1)
    await loadExtracts()
  }
  async function retryExtraction(documentId: string) {
    if (busy || finalised) return
    setBusy(true)
    setError(null)
    try {
      await retryEmptyDocument(documentId)
      await runCaseLinkSweep(caseReference)
      await onProcessed(documentId)
    } catch (e) {
      setError(getApiErrorMessage(e))
    } finally {
      try {
        await refresh()
      } catch (e) {
        setError(getApiErrorMessage(e))
      }
      setBusy(false)
    }
  }
  useEffect(() => {
    if (!showsExtracts) return
    let active = true
    void fetchClaimExtracts(caseReference)
      .then((payload) => {
        if (!active) return
        setExtracts(payload)
        setExtractsError(null)
      })
      .catch((e) => {
        if (!active) return
        setExtracts(null)
        setExtractsError(getApiErrorMessage(e))
      })
      .finally(() => {
        if (active) setExtractsLoading(false)
      })
    return () => {
      active = false
    }
  }, [caseReference, showsExtracts])
  useEffect(() => {
    let active = true
    void Promise.all([
      fetchCaseDocuments(caseReference),
      fetchClaimInvoices(caseReference),
    ])
      .then(([docs, rows]) => {
        if (active) {
          setDocuments(docs)
          setInvoices(rows)
        }
      })
      .catch((e) => {
        if (active) setError(getApiErrorMessage(e))
      })
    return () => {
      active = false
    }
  }, [caseReference])

  function describeProcessed(document: UploadedDocument) {
    if (document.manual_review) return "Needs review"
    if (document.kind === "engineer_assessment") {
      return document.paired
        ? "Engineer assessment linked"
        : "Engineer assessment awaiting a safe match"
    }
    return "Ingested"
  }

  /** A whole hand-over at once: a folder of repair invoices and a folder of
   * engineer assessments. The sequencing, the shared intake group, the per-file
   * isolation and the exactly-once sweep all live in `runIntakeBatch`, where
   * they can be tested without a browser; this only supplies the ports and
   * paints the result. */
  async function upload(group: IntakeGroup) {
    const invoiceFiles = files[group] ?? []
    const estimateFiles = takesAssessments(group) ? estimates : []
    // A later batch may supply only the missing assessments.
    if (busy || finalised || (!invoiceFiles.length && !estimateFiles.length)) return
    const batch: IntakeBatchEntry[] = [
      ...invoiceFiles.map((file) => ({ file, role: "invoice" as const })),
      ...estimateFiles.map((file) => ({ file, role: "estimate" as const })),
    ]
    const roleLabel = (role: IntakeBatchEntry["role"]) =>
      role === "estimate"
        ? "Engineer assessment"
        : takesAssessments(group)
          ? "Repair invoice"
          : "Client document"
    setBusy(true)
    setError(null)
    setFileFailures([])
    setSweepNotice(null)
    setResults(
      batch.map(({ file, role }) => ({
        name: file.name,
        role: roleLabel(role),
        status: "Queued",
      }))
    )
    try {
      const outcome = await runIntakeBatch(batch, caseReference, group, {
        upload: uploadCurrentDocument,
        process: processUploadedDocument,
        sweep: runCaseLinkSweep,
        errorMessage: getApiErrorMessage,
        describeProcessed,
        onStatus: (index, status) =>
          setResults((rows) =>
            rows.map((row, position) =>
              position === index ? { ...row, status } : row
            )
          ),
      })
      // Written before anything that can throw, and into its own state, so
      // that a failing refresh below cannot replace the one message naming
      // which files did not make it in.
      setFileFailures(outcome.failures)
      setSweepNotice(outcome.sweepError)
      try {
        await refresh()
        await onProcessed(outcome.firstInvoiceDocumentId)
      } catch (e) {
        setError(getApiErrorMessage(e))
      }
    } catch (e) {
      setError(getApiErrorMessage(e))
      await refresh().catch(() => undefined)
    } finally {
      setFiles((current) => ({ ...current, [group]: [] }))
      if (takesAssessments(group)) setEstimates([])
      setPickerKey((current) => current + 1)
      setBusy(false)
    }
  }
  const visibleInvoices = invoices.filter((row) =>
    groups.includes(row.intake_group as IntakeGroup)
  )
  const hasScopedDocuments =
    scope != null &&
    documents.some(
      (document) =>
        document.intake_group === scope && document.status === "ready"
    )
  return (
    <>
      {scope ? (
        <ScreenHeading
          title={scope === "live" ? "Upload new invoice" : labels[scope]}
          description={
            scope === "live"
              ? "Upload the new repair invoice and its engineer assessment. Review processing status, matching and extracts below, then continue to Benchmark analysis."
              : "Upload this source's repair invoices and engineer assessments. Review processing status, matching and extracts below."
          }
          action={
            <Button onClick={onContinue} disabled={busy}>
              Go to Document intelligence
            </Button>
          }
        />
      ) : (
        <ScreenHeading
          title={setup ? "Benchmark data setup" : "Document Intelligence"}
          description={
            setup
              ? "Build your reference dataset from client-provided documents. Keep one fresh invoice aside to run through Document Intelligence."
              : "Upload a fresh repair invoice, inspect its source pages, then review the extraction before benchmarking."
          }
          action={
            <Button
              onClick={onContinue}
              disabled={busy || (!setup && !visibleInvoices.length)}
            >
              {setup ? "Process a new invoice" : "Review source documents"}
            </Button>
          }
        />
      )}
      {fileFailures.length > 0 && (
        <Alert variant="destructive">
          <AlertTitle>
            {fileFailures.length}{" "}
            {fileFailures.length === 1 ? "file" : "files"} could not be
            processed
          </AlertTitle>
          <AlertDescription>
            Everything else in the hand-over was accepted. These were not:
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {fileFailures.map((failure, index) => (
                <li key={index}>{failure}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertTitle>Intake needs attention</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {sweepNotice && (
        <Alert>
          <AlertTitle>Documents stored, pairing sweep did not run</AlertTitle>
          <AlertDescription>
            Every file that was accepted is stored and extracted, but the
            case-wide link and gap-fill sweep failed: {sweepNotice} Nothing was
            lost and nothing needs re-uploading — invoices and engineer
            assessments may simply stay unpaired until Mapping review is
            approved, which runs the sweep again.
          </AlertDescription>
        </Alert>
      )}
      {finalised && (
        <Alert>
          <AlertTitle>Finalised case</AlertTitle>
          <AlertDescription>
            Create a new case revision to upload documents.
          </AlertDescription>
        </Alert>
      )}
      <div className="grid gap-5 lg:grid-cols-2">
        {groups.map((group) => (
          <Card key={group}>
            <CardHeader>
              <CardTitle>{labels[group]}</CardTitle>
              <CardDescription>
                {takesAssessments(group)
                  ? setup
                    ? "Upload client invoices and their corresponding engineer assessments. Hand over a whole set at once: every repair invoice, and every engineer assessment that goes with them. Pick files or a folder for each."
                    : "Hand over a whole set at once: every repair invoice, and every engineer assessment that goes with them. Pick files or a folder for each."
                  : "Upload client invoices and their corresponding engineer assessments. PDF and Word documents are supported."}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <label className="block space-y-2 text-sm font-medium">
                <span>
                  {takesAssessments(group)
                    ? "Repair invoices"
                    : labels[group]}
                </span>
                <Input
                  key={`files-${group}-${pickerKey}`}
                  type="file"
                  accept={accept}
                  multiple
                  disabled={busy || finalised}
                  onChange={(e) =>
                    setFiles((current) => ({
                      ...current,
                      [group]: Array.from(e.target.files ?? []).filter(
                        isSupportedDocument
                      ),
                    }))
                  }
                />
                <Input
                  key={`folder-${group}-${pickerKey}`}
                  aria-label={`${labels[group]} folder`}
                  type="file"
                  accept={accept}
                  multiple
                  disabled={busy || finalised}
                  {...directoryInputProps}
                  onChange={(e) =>
                    setFiles((current) => ({
                      ...current,
                      [group]: Array.from(e.target.files ?? []).filter(
                        isSupportedDocument
                      ),
                    }))
                  }
                />
                <span className="block font-normal text-muted-foreground">
                  {files[group]?.length
                    ? `${files[group]?.length} selected`
                    : "Choose files, or a whole folder."}
                </span>
              </label>
              {takesAssessments(group) && (
                <label className="block space-y-2 text-sm font-medium">
                  <span>Engineer assessments (optional)</span>
                  <Input
                    key={`estimates-${pickerKey}`}
                    type="file"
                    accept={accept}
                    multiple
                    disabled={busy || finalised}
                    onChange={(e) =>
                      setEstimates(
                        Array.from(e.target.files ?? []).filter(
                          isSupportedDocument
                        )
                      )
                    }
                  />
                  <Input
                    key={`estimates-folder-${pickerKey}`}
                    aria-label="Engineer assessments folder"
                    type="file"
                    accept={accept}
                    multiple
                    disabled={busy || finalised}
                    {...directoryInputProps}
                    onChange={(e) =>
                      setEstimates(
                        Array.from(e.target.files ?? []).filter(
                          isSupportedDocument
                        )
                      )
                    }
                  />
                  <span className="block font-normal text-muted-foreground">
                    {estimates.length
                      ? `${estimates.length} selected`
                      : "Choose files, or a whole folder."}
                  </span>
                </label>
              )}
              <Button
                disabled={busy || finalised || (!files[group]?.length && !estimates.length)}
                onClick={() => void upload(group)}
              >
                {busy
                  ? "Processing documents…"
                  : `Upload ${takesAssessments(group) ? "invoices and engineer assessments" : "documents"}`}
              </Button>
              {takesAssessments(group) &&
              !files[group]?.length &&
              estimates.length ? (
                <p className="text-sm text-amber-700 dark:text-amber-300">
                  You can add assessments separately. They will be matched to
                  invoices already uploaded in this source; unmatched assessments
                  remain available for review.
                </p>
              ) : null}
              {/* "What do you mean, nine invoices extracted? … remove it."
                  The counter used to read "16 documents processed · 9
                  invoices extracted" and nobody could say why the second
                  number was 9 -- it counted invoice *rows* in the group,
                  which diverges from the file count for reasons (a Word file
                  holding two invoices, a failed extraction, a document that
                  is an assessment rather than an invoice) the screen never
                  showed. The first half survives on its own because it is
                  one row per file handed over in this group and reached
                  `ready`: the Processing results table above names those
                  files one by one, so the number is checkable on the same
                  screen. */}
              <p className="text-sm text-muted-foreground">
                {
                  documents.filter(
                    (d) => d.intake_group === group && d.status === "ready"
                  ).length
                }{" "}
                documents processed
              </p>
              {documents.some((d) => d.intake_group === group && (d.invoice_units ?? 0) > 0) &&
               !documents.some((d) => d.intake_group === group && (d.assessment_units ?? 0) > 0) && (
                <Alert>
                  <AlertTitle>No engineer assessments in this source</AlertTitle>
                  <AlertDescription>
                    Invoices cannot pair until assessment files are uploaded and extracted here.
                    Select the assessment files in the Engineer assessments picker above, then upload.
                    Files marked stored can be processed from the receipt below.
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
      {documents.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Stored documents and extraction status</CardTitle>
            <CardDescription>
              This receipt stays available after refresh. Files in other sources
              are listed too, so a missing assessment can be located. Retry is
              available only when a file has no extracted records.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader><TableRow>
                <TableHead>File</TableHead><TableHead>Source</TableHead>
                <TableHead>Status</TableHead><TableHead>Extracted records</TableHead>
                <TableHead>Details</TableHead><TableHead>Action</TableHead>
              </TableRow></TableHeader>
              <TableBody>{documents.map((document) => (
                <TableRow key={document.id}>
                  <TableCell>{document.filename}</TableCell>
                  <TableCell>{document.intake_group ? labels[document.intake_group] : "Unassigned source"}</TableCell>
                  <TableCell>{document.status}</TableCell>
                  <TableCell>{document.extracted_invoice_units ?? document.invoice_units ?? 0} invoices · {document.assessment_units ?? 0} assessments</TableCell>
                  <TableCell>{document.processing_error || document.manual_review_reason || (
                    document.kind === "engineer_assessment"
                      ? document.paired ? "Assessment matched" : "Assessment extracted; no confirmed match"
                      : document.status === "ready" ? "Extraction complete" : "Awaiting extraction"
                  )}</TableCell>
                  <TableCell className="space-x-2">
                    {document.original_url && <a className="underline" href={document.original_url} target="_blank" rel="noreferrer">Original</a>}
                    {document.can_retry_extraction && <Button size="sm" variant="outline" disabled={busy || finalised} onClick={() => void retryExtraction(document.id)}>{document.status === "stored" ? "Process stored file" : "Retry extraction"}</Button>}
                    {document.manual_review && <Button size="sm" variant="outline" onClick={() => onOpenManualReview(document.id)}>Review</Button>}
                  </TableCell>
                </TableRow>
              ))}</TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
      {results.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Processing results</CardTitle>
            <CardDescription>
              One row per file, in the order they were sent. Invoices go first
              so the estimates behind them have something to link to.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>File</TableHead>
                  <TableHead>Handed over as</TableHead>
                  <TableHead>Result</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {/* Keyed by position, not filename: two folders can hand over
                    the same filename twice in one batch. */}
                {results.map((row, i) => (
                  <TableRow key={i}>
                    <TableCell>{row.name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {row.role}
                    </TableCell>
                    <TableCell role="status">{row.status}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
      {/* The reference-dataset receipt, and only on Benchmark data setup.
          On Document Intelligence this card was headed "Live invoices" over
          "Live invoices remain outside the reference dataset"; the client
          asked what it was, and it does not earn its place there -- the
          extracts tables below say the same thing about the same documents
          in the form she asked for. The setup variant is a different table
          about a different dataset and stays. */}
      {setup && (
        <Card>
          <CardHeader>
            <CardTitle>Consolidated client data</CardTitle>
            <CardDescription>
              Stored extraction from the selected client dataset. Ingestion
              prepares benchmark data; it does not train a model.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Source</TableHead>
                  <TableHead>Invoice</TableHead>
                  <TableHead>Repairer</TableHead>
                  <TableHead>Vehicle</TableHead>
                  <TableHead>Extracted lines</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleInvoices.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      {labels[row.intake_group as IntakeGroup]}
                    </TableCell>
                    <TableCell>
                      {row.invoice_number || row.document_filename}
                    </TableCell>
                    <TableCell>
                      {row.supplier_name || "Not extracted"}
                    </TableCell>
                    <TableCell>
                      {[row.vehicle?.make, row.vehicle?.model]
                        .filter(Boolean)
                        .join(" ") || "Not extracted"}
                    </TableCell>
                    <TableCell>{row.lines.length}</TableCell>
                  </TableRow>
                ))}
                {!visibleInvoices.length && (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="py-8 text-center text-muted-foreground"
                    >
                      No client reference invoices uploaded here yet.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
      {/* Lifted out of that card so removing it on Document Intelligence
          does not take with it the one line that explains the "Review
          <file>" buttons below. */}
      {documents.some(
        (d) => groups.includes(d.intake_group as IntakeGroup) && d.manual_review
      ) && (
        <p className="text-sm">
          <StatusBadge status="MANUAL REVIEW" /> Some documents need extraction
          review before they can supply benchmark evidence.
        </p>
      )}
      {/* The two standardised tables, on the screen people actually land on.
          They used to render only on Review findings, which now sits under
          Advanced tools, so nobody saw them. With the "Live invoices" card
          gone these are the receipt: the upload card is the action, and this
          is what the reviewer then reads. Deliberately not on the Benchmark
          data setup variant -- `/extracts` is case-scoped and unfiltered by
          intake group, so there it would show the live claim's
          invoice/assessment pairing on a screen whose every other table is
          filtered to the reference dataset. */}
      {showsExtracts && (
        <ExtractsSection
          extracts={extracts}
          loading={extractsLoading}
          error={extractsError}
        />
      )}
      {documents
        .filter(
          (d) =>
            groups.includes(d.intake_group as IntakeGroup) && d.manual_review
        )
        .map((d) => (
          <Button
            key={d.id}
            variant="outline"
            onClick={() => onOpenManualReview(d.id)}
          >
            Review {d.filename}
          </Button>
        ))}
      {scope && hasScopedDocuments ? (
        <SourceIntelligenceScreen
          key={`${receiptVersion}:${documents.filter((d) => d.intake_group === scope).map((d) => `${d.id}:${d.status}`).join("|")}`}
          caseReference={caseReference}
          intakeGroup={scope}
          finalised={finalised}
          onApproved={refresh}
          onOpenBenchmarks={onOpenBenchmarks ?? onContinue}
        />
      ) : null}
      {setup && (
        <Card>
          <CardHeader>
            <CardTitle>Extracted line items</CardTitle>
            <CardDescription>
              Consolidated structured rows from client invoices.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Invoice</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Quantity</TableHead>
                  <TableHead>Net amount</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleInvoices.flatMap((invoice) =>
                  invoice.lines.map((value, index) => {
                    const line = value as Record<string, unknown>
                    return (
                      <TableRow key={`${invoice.id}:${index}`}>
                        <TableCell>
                          {invoice.invoice_number || invoice.document_filename}
                        </TableCell>
                        <TableCell>
                          {String(
                            line.raw_description ??
                              line.description ??
                              "Not extracted"
                          )}
                        </TableCell>
                        <TableCell>{String(line.quantity ?? "—")}</TableCell>
                        <TableCell>
                          {String(line.line_total_net ?? "—")}
                        </TableCell>
                      </TableRow>
                    )
                  })
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </>
  )
}
