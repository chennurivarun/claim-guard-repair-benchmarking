import { useEffect, useState } from "react"
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
  fetchClaimInvoices,
  getApiErrorMessage,
  type ClaimInvoiceSummary,
} from "@/lib/api"
import {
  fetchCaseDocuments,
  processUploadedDocument,
  uploadCurrentDocument,
  type IntakeGroup,
  type UploadedDocument,
} from "./document-api"
import { ScreenHeading, StatusBadge } from "./shared"

const labels: Record<IntakeGroup, string> = {
  historical_claim: "Third-party claims invoices",
  in_house: "In-house repair invoices",
  live: "New repair invoice",
}
const accept = ".pdf,.doc,.docx"

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
  const [estimate, setEstimate] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<
    Array<{ name: string; status: string }>
  >([])
  const groups: IntakeGroup[] = setup
    ? ["historical_claim", "in_house"]
    : ["live"]

  async function refresh() {
    const [docs, rows] = await Promise.all([
      fetchCaseDocuments(caseReference),
      fetchClaimInvoices(caseReference),
    ])
    setDocuments(docs)
    setInvoices(rows)
  }
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

  async function upload(group: IntakeGroup) {
    const selected = files[group] ?? []
    if (busy || finalised || !selected.length) return
    const batch = [
      ...selected,
      ...(group === "live" && estimate ? [estimate] : []),
    ]
    setBusy(true)
    setError(null)
    setResults([])
    let invoiceDocumentId: string | undefined
    try {
      for (const file of batch) {
        setResults((rows) => [
          ...rows,
          { name: file.name, status: "Processing" },
        ])
        try {
          const doc = await uploadCurrentDocument(
            file,
            caseReference,
            group,
            file === estimate ? invoiceDocumentId : undefined
          )
          const result = await processUploadedDocument(doc.id)
          if (result.document.kind === "repair_invoice")
            invoiceDocumentId = doc.id
          setResults((rows) =>
            rows.map((row) =>
              row.name === file.name
                ? {
                    ...row,
                    status: result.document.manual_review
                      ? "Needs review"
                      : result.document.kind === "engineer_assessment"
                        ? result.document.paired
                          ? "Estimate linked"
                          : "Estimate awaiting a safe match"
                        : "Ingested",
                  }
                : row
            )
          )
        } catch (e) {
          setResults((rows) =>
            rows.map((row) =>
              row.name === file.name
                ? { ...row, status: getApiErrorMessage(e) }
                : row
            )
          )
          throw e
        }
      }
      await refresh()
      await onProcessed(invoiceDocumentId)
      setFiles((current) => ({ ...current, [group]: [] }))
      if (group === "live") setEstimate(null)
    } catch (e) {
      setError(getApiErrorMessage(e))
      await refresh().catch(() => undefined)
    } finally {
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
                  ? "One invoice, with an optional engineer estimate."
                  : "Upload client invoices and their corresponding engineer estimates. PDF and Word documents are supported."}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <label className="block space-y-2 text-sm font-medium">
                <span>
                  {group === "live"
                    ? "Repair invoice (required)"
                    : labels[group]}
                </span>
                <Input
                  type="file"
                  accept={accept}
                  multiple={setup}
                  disabled={busy || finalised}
                  onChange={(e) =>
                    setFiles((current) => ({
                      ...current,
                      [group]: Array.from(e.target.files ?? []),
                    }))
                  }
                />
              </label>
              {group === "live" && (
                <label className="block space-y-2 text-sm font-medium">
                  <span>Engineer estimate (optional)</span>
                  <Input
                    type="file"
                    accept={accept}
                    disabled={busy || finalised}
                    onChange={(e) => setEstimate(e.target.files?.[0] ?? null)}
                  />
                </label>
              )}
              <Button
                disabled={busy || finalised || !files[group]?.length}
                onClick={() => void upload(group)}
              >
                {busy
                  ? "Processing documents…"
                  : `Upload ${group === "live" ? "invoice" : "documents"}`}
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
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>File</TableHead>
                  <TableHead>Result</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((row, i) => (
                  <TableRow key={i}>
                    <TableCell>{row.name}</TableCell>
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
