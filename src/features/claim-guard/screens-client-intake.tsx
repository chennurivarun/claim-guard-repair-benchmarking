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
  runCaseLinkSweep,
  uploadCurrentDocument,
  type IntakeGroup,
  type UploadedDocument,
} from "./document-api"
import { ExtractsSection } from "./extracts-section"
import { runIntakeBatch, type IntakeBatchEntry } from "./intake-batch"
import { ScreenHeading, StatusBadge } from "./shared"

const labels: Record<IntakeGroup, string> = {
  historical_claim: "Third-party claims invoices",
  in_house: "In-house repair invoices",
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

export function ClientIntakeScreen({
  caseReference,
  setup,
  finalised,
  onProcessed,
  onContinue,
  onOpenManualReview,
}: {
  caseReference: string
  setup: boolean
  finalised: boolean
  onProcessed: (documentId?: string) => Promise<void>
  onContinue: () => void
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
  const [sweepResult, setSweepResult] = useState<string | null>(null)
  const [sweeping, setSweeping] = useState(false)
  const [results, setResults] = useState<
    Array<{ name: string; role: string; status: string }>
  >([])
  /** Bumped after every batch so the file inputs drop their DOM selection:
   * without it, re-picking the same folder fires no `change` event. */
  const [pickerKey, setPickerKey] = useState(0)
  const [extracts, setExtracts] = useState<ClaimExtractsPayload | null>(null)
  const [extractsLoading, setExtractsLoading] = useState(!setup)
  const [extractsError, setExtractsError] = useState<string | null>(null)
  const groups: IntakeGroup[] = setup
    ? ["historical_claim", "in_house"]
    : ["live"]

  /** The extracts endpoint is case-scoped, so it only means something on the
   * live screen; see the `!setup` guard on the section itself. */
  async function loadExtracts() {
    if (setup) return
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
    await loadExtracts()
  }
  useEffect(() => {
    if (setup) return
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
  }, [caseReference, setup])
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

  /** Re-run the case-wide link / gap-fill sweep on what is already in the
   * claim. The sweep is idempotent -- `run_case_gap_fill` reverses its own
   * earlier writes before re-evaluating -- so this is safe to press again,
   * and it is the only way out of a failed sweep that does not involve
   * re-uploading every file. It uploads nothing and touches no handler
   * decision. */
  async function rerunSweep() {
    if (sweeping || busy || finalised) return
    setSweeping(true)
    setSweepNotice(null)
    setSweepResult(null)
    try {
      const summary = await runCaseLinkSweep(caseReference)
      setSweepResult(
        `Pairing sweep finished: ${summary.paired} of ${summary.assessments} engineer estimates are linked to an invoice.`
      )
      await refresh()
      await onProcessed()
    } catch (e) {
      setSweepNotice(getApiErrorMessage(e))
    } finally {
      setSweeping(false)
    }
  }

  /** A whole hand-over at once: a folder of repair invoices and a folder of
   * engineer assessments. The sequencing, the shared intake group, the per-file
   * isolation and the exactly-once sweep all live in `runIntakeBatch`, where
   * they can be tested without a browser; this only supplies the ports and
   * paints the result. */
  async function upload(group: IntakeGroup) {
    const invoiceFiles = files[group] ?? []
    const estimateFiles = group === "live" ? estimates : []
    // Engineer assessments alone are refused: they would upload with nothing
    // in the case to pair against, and the label above the picker says
    // invoices are required.
    if (busy || finalised || !invoiceFiles.length) return
    const batch: IntakeBatchEntry[] = [
      ...invoiceFiles.map((file) => ({ file, role: "invoice" as const })),
      ...estimateFiles.map((file) => ({ file, role: "estimate" as const })),
    ]
    const roleLabel = (role: IntakeBatchEntry["role"]) =>
      role === "estimate"
        ? "Engineer assessment"
        : group === "live"
          ? "Repair invoice"
          : "Client document"
    setBusy(true)
    setError(null)
    setFileFailures([])
    setSweepNotice(null)
    setSweepResult(null)
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
      if (group === "live") setEstimates([])
      setPickerKey((current) => current + 1)
      setBusy(false)
    }
  }
  const visibleInvoices = invoices.filter((row) =>
    groups.includes(row.intake_group as IntakeGroup)
  )
  return (
    <>
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
            assessments may simply stay unpaired until the sweep is re-run
            below.
          </AlertDescription>
        </Alert>
      )}
      {sweepResult && (
        <Alert>
          <AlertTitle>Pairing sweep complete</AlertTitle>
          <AlertDescription>{sweepResult}</AlertDescription>
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
                {group === "live"
                  ? "Hand over a whole set at once: every repair invoice, and every engineer assessment that goes with them. Pick files or a folder for each."
                  : "Upload client invoices and their corresponding engineer assessments. PDF and Word documents are supported."}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <label className="block space-y-2 text-sm font-medium">
                <span>
                  {group === "live"
                    ? "Repair invoices (required)"
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
              {group === "live" && (
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
              {/* Invoices are required, and the gate says so. It used to pass
                  on engineer assessments alone, which uploaded a folder of
                  them into a case with nothing to pair them against. */}
              <Button
                disabled={busy || finalised || !files[group]?.length}
                onClick={() => void upload(group)}
              >
                {busy
                  ? "Processing documents…"
                  : `Upload ${group === "live" ? "invoices and engineer assessments" : "documents"}`}
              </Button>
              {group === "live" && !files[group]?.length && estimates.length ? (
                <p className="text-sm text-amber-700 dark:text-amber-300">
                  Add the repair invoices these engineer assessments belong to.
                  An engineer assessment uploaded on its own has nothing to
                  pair against.
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
            </CardContent>
          </Card>
        ))}
      </div>
      {/* The sweep is the one step of the hand-over that can fail on its own
          without losing a file, so it is the one step that needs its own
          control. Standing, not only offered after a failure: a sweep that
          ran before the last estimate finished extracting, or against a case
          whose invoices arrived in an earlier batch, is re-run from here
          rather than by uploading everything again. */}
      {!setup && (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            disabled={busy || sweeping || finalised}
            onClick={() => void rerunSweep()}
          >
            {sweeping ? "Re-running pairing sweep…" : "Re-run pairing sweep"}
          </Button>
          <p className="text-sm text-muted-foreground">
            Re-pairs every invoice and engineer estimate already in this claim.
            Uploads nothing, changes no handler decision, and is safe to run
            again at any time.
          </p>
        </div>
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
      {!setup && (
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
