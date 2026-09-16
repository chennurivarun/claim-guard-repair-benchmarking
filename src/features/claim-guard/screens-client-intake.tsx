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

/** One row of the hand-over, in the order it will be sent. */
type BatchEntry = { file: File; role: "invoice" | "estimate" }

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
  const [sweepNotice, setSweepNotice] = useState<string | null>(null)
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
      return document.paired ? "Estimate linked" : "Estimate awaiting a safe match"
    }
    return "Ingested"
  }

  /** A whole hand-over at once: a folder of repair invoices and a folder of
   * engineer estimates. The sequencing matters and is deliberate.
   *
   * 1. Every invoice goes first, then every estimate -- an estimate can only
   *    be linked to an invoice the case already holds.
   * 2. Every file is uploaded under the same `intake_group`. The backend
   *    refuses to pair an estimate with an invoice from another group, so a
   *    mixed-group hand-over would silently never pair.
   * 3. A file that fails does not abort the batch. A folder of ten is not
   *    worth losing to one unreadable scan; the failure is reported on its
   *    own row and summarised at the end.
   * 4. The case-wide link / gap-fill sweep runs exactly **once**, after the
   *    last file. See `runCaseLinkSweep`. */
  async function upload(group: IntakeGroup) {
    const invoiceFiles = files[group] ?? []
    const estimateFiles = group === "live" ? estimates : []
    if (busy || finalised || (!invoiceFiles.length && !estimateFiles.length))
      return
    const batch: BatchEntry[] = [
      ...invoiceFiles.map((file) => ({ file, role: "invoice" as const })),
      ...estimateFiles.map((file) => ({ file, role: "estimate" as const })),
    ]
    const roleLabel = (role: BatchEntry["role"]) =>
      role === "estimate"
        ? "Engineer estimate"
        : group === "live"
          ? "Repair invoice"
          : "Client document"
    setBusy(true)
    setError(null)
    setSweepNotice(null)
    setResults(
      batch.map(({ file, role }) => ({
        name: file.name,
        role: roleLabel(role),
        status: "Queued",
      }))
    )
    const setStatus = (index: number, status: string) =>
      setResults((rows) =>
        rows.map((row, position) =>
          position === index ? { ...row, status } : row
        )
      )
    // The backend only accepts an explicit invoice link when the estimate
    // names a single-invoice document, so the hint is kept for the one
    // invoice + one estimate hand-over that used to be the only option. With
    // a folder of each, which estimate belongs to which invoice is the
    // sweep's job -- it sees the whole set, this loop does not.
    const explicitPairing =
      invoiceFiles.length === 1 && estimateFiles.length === 1
    let pairTarget: string | undefined
    // The reviewer is sent to the first invoice of the hand-over: with a
    // folder, any other choice is alphabetical accident.
    let firstInvoiceDocumentId: string | undefined
    const failures: string[] = []
    try {
      for (const [index, { file, role }] of batch.entries()) {
        setStatus(index, `Uploading (${index + 1} of ${batch.length})`)
        try {
          const doc = await uploadCurrentDocument(
            file,
            caseReference,
            group,
            role === "estimate" && explicitPairing ? pairTarget : undefined
          )
          setStatus(index, "Extracting…")
          const result = await processUploadedDocument(doc.id)
          if (result.document.kind === "repair_invoice") {
            pairTarget ??= doc.id
            firstInvoiceDocumentId ??= doc.id
          }
          setStatus(index, describeProcessed(result.document))
        } catch (e) {
          const message = getApiErrorMessage(e)
          failures.push(`${file.name}: ${message}`)
          setStatus(index, message)
        }
      }
      if (failures.length < batch.length) {
        try {
          await runCaseLinkSweep(caseReference)
        } catch (e) {
          // The documents are stored either way; only the pairing pass is
          // missing, and it can be re-run. Say so instead of presenting the
          // whole hand-over as failed.
          setSweepNotice(getApiErrorMessage(e))
        }
      }
      if (failures.length) {
        setError(
          `${failures.length} of ${batch.length} files could not be processed. ${failures.join(" · ")}`
        )
      }
      await refresh()
      await onProcessed(firstInvoiceDocumentId)
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
            ? "Build your reference dataset from client-provided documents. Keep one fresh invoice aside for the live demonstration."
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
            Every file was ingested, but the case-wide link and gap-fill sweep
            failed: {sweepNotice} Invoices and estimates may stay unpaired
            until it is re-run.
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
                {group === "live"
                  ? "Hand over a whole set at once: every repair invoice, and every engineer estimate that goes with them. Pick files or a folder for each."
                  : "Upload client invoices and their corresponding engineer estimates. PDF and Word documents are supported."}
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
                      [group]: Array.from(e.target.files ?? []),
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
                  <span>Engineer estimates (optional)</span>
                  <Input
                    key={`estimates-${pickerKey}`}
                    type="file"
                    accept={accept}
                    multiple
                    disabled={busy || finalised}
                    onChange={(e) =>
                      setEstimates(Array.from(e.target.files ?? []))
                    }
                  />
                  <Input
                    key={`estimates-folder-${pickerKey}`}
                    aria-label="Engineer estimates folder"
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
                disabled={
                  busy ||
                  finalised ||
                  !(files[group]?.length || (group === "live" && estimates.length))
                }
                onClick={() => void upload(group)}
              >
                {busy
                  ? "Processing documents…"
                  : `Upload ${group === "live" ? "invoices and estimates" : "documents"}`}
              </Button>
              <p className="text-sm text-muted-foreground">
                {
                  documents.filter(
                    (d) => d.intake_group === group && d.status === "ready"
                  ).length
                }{" "}
                documents processed ·{" "}
                {invoices.filter((i) => i.intake_group === group).length}{" "}
                invoices extracted
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
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
      <Card>
        <CardHeader>
          <CardTitle>
            {setup ? "Consolidated client data" : "Live invoices"}
          </CardTitle>
          <CardDescription>
            {setup
              ? "Stored extraction from the selected client dataset. Ingestion prepares benchmark data; it does not train a model."
              : "Live invoices remain outside the reference dataset."}
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
                  <TableCell>{row.supplier_name || "Not extracted"}</TableCell>
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
                    {setup
                      ? "No client reference invoices uploaded here yet."
                      : "No live invoices uploaded yet. Upload a fresh repair invoice to begin."}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          {documents.some(
            (d) =>
              groups.includes(d.intake_group as IntakeGroup) && d.manual_review
          ) && (
            <p className="mt-4 text-sm">
              <StatusBadge status="MANUAL REVIEW" /> Some documents need
              extraction review before they can supply benchmark evidence.
            </p>
          )}
        </CardContent>
      </Card>
      {/* The two standardised tables and the per-total split, on the screen
          people actually land on. They used to render only on Review
          findings, which now sits under Advanced tools, so nobody saw them.
          Placed directly under the Live invoices table: the upload card is
          the action, that table is the receipt, and this is what the reviewer
          then reads. Deliberately not on the Benchmark data setup variant --
          `/extracts` is case-scoped and unfiltered by intake group, so there
          it would show the live claim's invoice/assessment pairing on a
          screen whose every other table is filtered to the reference
          dataset. */}
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
