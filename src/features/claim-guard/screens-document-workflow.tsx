import { useEffect, useState } from "react"
import type { FormEvent, InputHTMLAttributes } from "react"
import {
  AlertCircleIcon,
  ArrowRightIcon,
  FileCheck2Icon,
  FileSpreadsheetIcon,
  FileTextIcon,
  LoaderCircleIcon,
  LockKeyholeIcon,
  PencilLineIcon,
  RefreshCwIcon,
  SaveIcon,
  UploadCloudIcon,
} from "lucide-react"
import { toast } from "sonner"
import { fetchDataReadiness, type DataReadinessPayload } from "@/lib/api"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"

import {
  correctDocumentPage,
  documentApiErrorMessage,
  documentImageUrl,
  fetchDocumentPages,
  PAGE_TYPES,
  processUploadedDocument,
  uploadCurrentDocument,
} from "./document-api"
import type {
  DocumentPageRecord,
  DocumentPageType,
  DocumentProcessingResult,
} from "./document-api"
import { DataCard, ScreenHeading, StatusBadge } from "./shared"

function humanise(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

function isSupportedDocument(file: File) {
  const name = file.name.toLowerCase()
  return [".pdf", ".doc", ".docx"].some((extension) => name.endsWith(extension))
}

const supportedDocumentTypes =
  "application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.pdf,.doc,.docx"

const directoryInputProps = {
  webkitdirectory: "",
  directory: "",
} as InputHTMLAttributes<HTMLInputElement>

function ReusableBankCard({
  title,
  description,
  status,
  detail,
  icon: Icon,
  actionLabel,
  onAction,
}: {
  title: string
  description: string
  status: string
  detail: string
  icon: typeof FileSpreadsheetIcon
  actionLabel?: string
  onAction?: () => void
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
              <Icon className="size-5" aria-hidden />
            </span>
            <div className="min-w-0">
              <CardTitle>{title}</CardTitle>
              <CardDescription>{description}</CardDescription>
            </div>
          </div>
          <StatusBadge status={status} />
        </div>
      </CardHeader>
      <CardContent>
        <p className="truncate text-sm font-medium">{detail}</p>
      </CardContent>
      <CardFooter className="justify-between gap-3">
        <Badge variant="outline">Active bank reused</Badge>
        {actionLabel && onAction ? (
          <Button type="button" size="sm" variant="outline" onClick={onAction}>
            {actionLabel}
          </Button>
        ) : null}
      </CardFooter>
    </Card>
  )
}

function CurrentInvoiceCard({
  currentDocument,
  pageCount,
  selectedFiles,
  onFilesChange,
  onSubmit,
  busy,
  progress,
  progressMessage,
  error,
  finalised,
}: {
  currentDocument: string | null
  pageCount: number
  selectedFiles: File[]
  onFilesChange: (files: File[]) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  busy: boolean
  progress: number
  progressMessage: string
  error: string | null
  finalised: boolean
}) {
  return (
    <Card>
      <form onSubmit={onSubmit}>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 items-start gap-3">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                <FileTextIcon className="size-5" aria-hidden />
              </span>
              <div className="min-w-0">
                <CardTitle>Current repair invoice</CardTitle>
                <CardDescription>
                  Upload a PDF or Word document and run the layered extraction
                  pipeline.
                </CardDescription>
              </div>
            </div>
            <StatusBadge
              status={
                busy ? "PROCESSING" : currentDocument ? "READY" : "REQUIRED"
              }
            />
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <FieldGroup>
            <Field data-invalid={Boolean(error)}>
              <FieldLabel htmlFor="repair-invoice-pdf">
                Repair invoice or assessment
              </FieldLabel>
              <Input
                id="repair-invoice-pdf"
                type="file"
                accept={supportedDocumentTypes}
                multiple
                aria-invalid={Boolean(error)}
                disabled={busy || finalised}
                onChange={(event) =>
                  onFilesChange(Array.from(event.target.files ?? []))
                }
              />
              <FieldDescription>
                {selectedFiles.length
                  ? `${selectedFiles.length} document${selectedFiles.length === 1 ? "" : "s"} selected`
                  : currentDocument
                    ? `${currentDocument} · ${pageCount} page${pageCount === 1 ? "" : "s"} available`
                    : "Choose PDF, DOC, or DOCX files. Word files are converted to PDF before extraction."}
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="repair-invoice-folder">
                Or choose a folder
              </FieldLabel>
              <Input
                id="repair-invoice-folder"
                type="file"
                accept={supportedDocumentTypes}
                multiple
                disabled={busy || finalised}
                {...directoryInputProps}
                onChange={(event) =>
                  onFilesChange(
                    Array.from(event.target.files ?? []).filter(
                      isSupportedDocument
                    )
                  )
                }
              />
              <FieldDescription>
                All supported documents in the selected folder are queued
                separately.
              </FieldDescription>
            </Field>
          </FieldGroup>

          {progress > 0 ? (
            <div className="flex flex-col gap-2" aria-live="polite">
              <div className="flex items-center justify-between gap-4 text-sm">
                <span>{progressMessage}</span>
                <span className="text-muted-foreground tabular-nums">
                  {progress}%
                </span>
              </div>
              <Progress value={progress} aria-label={progressMessage} />
            </div>
          ) : null}

          {error ? (
            <Alert variant="destructive">
              <AlertCircleIcon />
              <AlertTitle>Upload or processing failed</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
        </CardContent>
        <CardFooter>
          <Button
            type="submit"
            size="sm"
            disabled={!selectedFiles.length || busy || finalised}
          >
            {busy ? (
              <LoaderCircleIcon
                data-icon="inline-start"
                className="animate-spin"
              />
            ) : (
              <UploadCloudIcon data-icon="inline-start" />
            )}
            {finalised
              ? "Case is finalised"
              : busy
                ? "Processing invoices"
                : "Upload and process"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  )
}

export function UploadProcessingWorkflow({
  caseReference,
  finalised,
  onProcessed,
  onContinue,
  onOpenOntologyLibrary,
}: {
  caseReference: string
  finalised: boolean
  onProcessed: () => Promise<void>
  onContinue: () => void
  onOpenOntologyLibrary: () => void
}) {
  const [pages, setPages] = useState<DocumentPageRecord[]>([])
  const [pageLoadError, setPageLoadError] = useState<string | null>(null)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [progressMessage, setProgressMessage] = useState("")
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [processingResult, setProcessingResult] =
    useState<DocumentProcessingResult | null>(null)
  const [readiness, setReadiness] = useState<DataReadinessPayload | null>(null)
  const [batchRows, setBatchRows] = useState<
    Array<{ id: string; name: string; status: string; detail: string }>
  >([])

  useEffect(() => {
    let active = true
    void Promise.all([fetchDocumentPages(caseReference), fetchDataReadiness()])
      .then(([records, ready]) => {
        if (!active) return
        setPages(records)
        setReadiness(ready)
        setPageLoadError(null)
      })
      .catch((error: unknown) => {
        if (active) setPageLoadError(documentApiErrorMessage(error))
      })
    return () => {
      active = false
    }
  }, [caseReference])

  const latestPage = pages[pages.length - 1]
  const currentDocument = latestPage?.document_filename ?? null
  const currentDocumentPages = latestPage
    ? pages.filter((page) => page.document_id === latestPage.document_id)
    : []
  const extractionMethods = Array.from(
    new Set(
      currentDocumentPages.map((page) => humanise(page.extraction_method))
    )
  ).join(", ")
  const correctedPages = currentDocumentPages.filter(
    (page) => page.classification_source === "handler"
  ).length
  const metrics = processingResult?.metrics
  const processingRows: Array<[string, string, string, string]> = [
    [
      "File intake",
      "SHA-256 + PDF signature validation",
      currentDocument ?? "Waiting for a current repair invoice",
      currentDocument ? "PASS" : "PENDING",
    ],
    [
      "Page classification",
      extractionMethods || "Native text before OCR",
      currentDocumentPages.length
        ? `${currentDocumentPages.length} page${currentDocumentPages.length === 1 ? "" : "s"} classified`
        : "No processed pages yet",
      currentDocumentPages.length ? "PASS" : "PENDING",
    ],
    [
      "Invoice extraction",
      "Deterministic table and calculation pipeline",
      metrics
        ? `${metrics.invoice_units} invoice unit${metrics.invoice_units === 1 ? "" : "s"} · ${metrics.extracted_lines} lines`
        : currentDocumentPages.length
          ? "Existing extraction is available"
          : "Runs after page classification",
      currentDocumentPages.length ? "PASS" : "PENDING",
    ],
    [
      "Handler review",
      "Audited page corrections",
      correctedPages
        ? `${correctedPages} corrected page${correctedPages === 1 ? "" : "s"}`
        : "No page corrections",
      correctedPages
        ? "REVIEW"
        : currentDocumentPages.length
          ? "PASS"
          : "PENDING",
    ],
  ]

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (finalised) {
      setUploadError(
        "This case is finalised. Create a new case revision before uploading another invoice."
      )
      return
    }
    if (!selectedFiles.length) return
    const invalid = selectedFiles.find((file) => !isSupportedDocument(file))
    if (invalid) {
      setUploadError(
        `${invalid.name} is not a supported PDF, DOC, or DOCX document.`
      )
      return
    }

    setBusy(true)
    setUploadError(null)
    setBatchRows(
      selectedFiles.map((file, index) => ({
        id: `${index}:${file.name}`,
        name: file.name,
        status: "QUEUED",
        detail: "Waiting",
      }))
    )
    try {
      let latestResult: DocumentProcessingResult | null = null
      for (const [index, file] of selectedFiles.entries()) {
        const batchRowId = `${index}:${file.name}`
        const itemProgress = Math.round((index / selectedFiles.length) * 85)
        setProgress(Math.max(itemProgress, 5))
        setProgressMessage(
          `Processing ${index + 1} of ${selectedFiles.length}: ${file.name}`
        )
        setBatchRows((current) =>
          current.map((row) =>
            row.id === batchRowId
              ? {
                  ...row,
                  status: "PROCESSING",
                  detail: "Uploading and extracting",
                }
              : row
          )
        )
        try {
          const uploaded = await uploadCurrentDocument(file, caseReference)
          latestResult = await processUploadedDocument(uploaded.id)
          setBatchRows((current) =>
            current.map((row) =>
              row.id === batchRowId
                ? {
                    ...row,
                    status: "READY",
                    detail:
                      latestResult?.document.kind === "engineer_assessment"
                        ? `Engineer assessment${latestResult.document.paired ? " · paired" : " · awaiting matching invoice"}`
                        : `${latestResult?.metrics?.invoice_units ?? 0} repair invoice unit(s)`,
                  }
                : row
            )
          )
        } catch (error) {
          setBatchRows((current) =>
            current.map((row) =>
              row.id === batchRowId
                ? {
                    ...row,
                    status: "FAILED",
                    detail: documentApiErrorMessage(error),
                  }
                : row
            )
          )
        }
      }
      setProcessingResult(latestResult)
      setProgress(90)
      setProgressMessage("Refreshing invoice list and document pages")
      const refreshedPages = await fetchDocumentPages(caseReference)
      setPages(refreshedPages)
      setPageLoadError(null)
      if (latestResult) await onProcessed()
      setProgress(100)
      setProgressMessage("Batch processing complete")
      toast.success("Document batch processing completed", {
        description: `${selectedFiles.length} file${selectedFiles.length === 1 ? "" : "s"} checked. Review each status below.`,
      })
    } catch (error) {
      setUploadError(documentApiErrorMessage(error))
      setProgress(0)
      setProgressMessage("")
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <ScreenHeading
        title="Upload & Processing"
        description="Upload repair invoices and matching Engineer Assessments as PDF, DOC, or DOCX. Each document is classified, retained and kept auditable."
        action={
          <Button onClick={onContinue} disabled={busy}>
            View benchmarks
            <ArrowRightIcon data-icon="inline-end" />
          </Button>
        }
      />

      <Alert>
        <LockKeyholeIcon />
        <AlertTitle>Draft analysis is available</AlertTitle>
        <AlertDescription>
          PDF extraction and price analysis may continue regardless of
          liability. A challenge can only be issued later when liability is
          handler-confirmed ADMITTED or SPLIT LIABILITY.
        </AlertDescription>
      </Alert>

      {finalised ? (
        <Alert>
          <LockKeyholeIcon />
          <AlertTitle>Finalised case is read-only</AlertTitle>
          <AlertDescription>
            Existing invoices remain available for review and download. Create a
            new case revision before adding or reprocessing documents.
          </AlertDescription>
        </Alert>
      ) : null}

      {pageLoadError ? (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>Document service unavailable</AlertTitle>
          <AlertDescription>{pageLoadError}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <CurrentInvoiceCard
          currentDocument={currentDocument}
          pageCount={currentDocumentPages.length}
          selectedFiles={selectedFiles}
          onFilesChange={(files) => {
            setSelectedFiles(files)
            setUploadError(
              files.some((file) => !isSupportedDocument(file))
                ? "Every selected file must be PDF, DOC, or DOCX."
                : null
            )
          }}
          onSubmit={handleUpload}
          busy={busy}
          progress={progress}
          progressMessage={progressMessage}
          error={uploadError}
          finalised={finalised}
        />
        <ReusableBankCard
          title="Ontology / reference bank"
          description="Optional pilot or admin import"
          status={readiness?.ontology_items ? "ACTIVE" : "MISSING"}
          detail={`${readiness?.ontology_items ?? 0} ontology items · active bank reused`}
          icon={FileSpreadsheetIcon}
          actionLabel="Open library"
          onAction={onOpenOntologyLibrary}
        />
        <ReusableBankCard
          title="Previous invoice bank"
          description="Optional supporting evidence"
          status={readiness?.historical_claims ? "READY" : "MISSING"}
          detail={`${readiness?.historical_claims ?? 0} previous repair & service lines`}
          icon={UploadCloudIcon}
        />
      </div>

      {readiness && !readiness.ready ? (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>Reference data is not ready</AlertTitle>
          <AlertDescription>{readiness.issues.join(" ")}</AlertDescription>
        </Alert>
      ) : null}

      {batchRows.length ? (
        <DataCard
          title="Document batch"
          description="Each document is retained separately and classified as a repair invoice or Engineer Assessment."
        >
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Document file</TableHead>
                  <TableHead>Result</TableHead>
                  <TableHead className="text-right">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {batchRows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium">{row.name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {row.detail}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <StatusBadge status={row.status} />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </DataCard>
      ) : null}

      <DataCard
        title="Processing run"
        description="Live status from the PDF pipeline for this case."
      >
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Stage</TableHead>
                <TableHead>Method</TableHead>
                <TableHead>Result</TableHead>
                <TableHead className="text-right">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {processingRows.map(([stage, method, result, status]) => (
                <TableRow key={stage}>
                  <TableCell className="font-medium">{stage}</TableCell>
                  <TableCell>{method}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {result}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end">
                      <StatusBadge status={status} />
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </DataCard>
    </>
  )
}

interface PageCorrectionDraft {
  actor: string
  reason: string
  pageType: DocumentPageType
  groupId: string
  rotation: string
}

export function DocumentPagesWorkflow({
  onContinue,
}: {
  onContinue: () => void
}) {
  const [pages, setPages] = useState<DocumentPageRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selectedPage, setSelectedPage] = useState<DocumentPageRecord | null>(
    null
  )
  const [saving, setSaving] = useState(false)
  const [reprocessing, setReprocessing] = useState(false)
  const [correctionError, setCorrectionError] = useState<string | null>(null)
  const [draft, setDraft] = useState<PageCorrectionDraft>({
    actor: "pilot.handler",
    reason: "",
    pageType: "other",
    groupId: "",
    rotation: "0",
  })

  useEffect(() => {
    let active = true
    void fetchDocumentPages()
      .then((records) => {
        if (!active) return
        setPages(records)
        setLoadError(null)
        setLoading(false)
      })
      .catch((error: unknown) => {
        if (!active) return
        setLoadError(documentApiErrorMessage(error))
        setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const documentNames = Array.from(
    new Set(pages.map((page) => page.document_filename))
  )
  const invoiceGroups = new Set(
    pages
      .filter((page) => page.page_type === "invoice")
      .map((page) => page.group_id ?? `${page.document_id}:${page.page_number}`)
  )
  const reprocessRequired = pages.some((page) => page.reprocess_required)

  async function handleReprocess() {
    const documentIds = Array.from(
      new Set(
        pages
          .filter((page) => page.reprocess_required)
          .map((page) => page.document_id)
      )
    )
    setReprocessing(true)
    setLoadError(null)
    try {
      for (const documentId of documentIds) {
        await processUploadedDocument(documentId, true)
      }
      setPages(await fetchDocumentPages())
      toast.success("Corrected document reprocessed", {
        description:
          "Invoice grouping and extraction now use the saved page corrections.",
      })
    } catch (error) {
      setLoadError(documentApiErrorMessage(error))
    } finally {
      setReprocessing(false)
    }
  }

  function openCorrection(page: DocumentPageRecord) {
    setSelectedPage(page)
    setCorrectionError(null)
    setDraft({
      actor: page.correction?.corrected_by ?? "pilot.handler",
      reason: "",
      pageType: page.page_type,
      groupId: page.group_id ?? "",
      rotation: String(page.rotation),
    })
  }

  async function handleCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedPage) return
    setSaving(true)
    setCorrectionError(null)
    try {
      const corrected = await correctDocumentPage(selectedPage.id, {
        actor: draft.actor.trim(),
        reason: draft.reason.trim(),
        pageType: draft.pageType,
        groupId: draft.groupId.trim() || null,
        rotation: Number(draft.rotation),
      })
      setPages((current) =>
        current.map((page) => (page.id === corrected.id ? corrected : page))
      )
      setSelectedPage(null)
      toast.success(`Page ${corrected.page_number} correction saved`, {
        description:
          "The original machine extraction remains in the audit trail.",
      })
      if (corrected.reprocess_required) {
        toast.warning("Document reprocessing required", {
          description:
            "Existing invoice grouping remains draft until the PDF pipeline is rerun.",
        })
      }
    } catch (error) {
      setCorrectionError(documentApiErrorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <ScreenHeading
        title="Document Pages"
        description="Review live page images, machine classifications and handler corrections before extraction."
        action={
          <Button
            onClick={onContinue}
            disabled={!pages.length || reprocessRequired}
          >
            Review extraction
            <ArrowRightIcon data-icon="inline-end" />
          </Button>
        }
      />

      {loadError ? (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>Document pages could not be loaded</AlertTitle>
          <AlertDescription>{loadError}</AlertDescription>
        </Alert>
      ) : null}

      {reprocessRequired ? (
        <Alert>
          <RefreshCwIcon />
          <AlertTitle>
            Reprocessing required before extraction review
          </AlertTitle>
          <AlertDescription>
            A handler changed page classification, grouping or rotation. The
            corrected page is saved and audited; existing invoice units remain
            draft until the PDF pipeline is rerun.
            <Button
              className="mt-2 ml-3"
              size="sm"
              variant="outline"
              disabled={reprocessing}
              onClick={() => void handleReprocess()}
            >
              <RefreshCwIcon
                data-icon="inline-start"
                className={reprocessing ? "animate-spin" : undefined}
              />
              {reprocessing ? "Reprocessing" : "Reprocess corrected document"}
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      <DataCard
        title={
          documentNames.length === 1
            ? documentNames[0]
            : `${documentNames.length} processed documents`
        }
        description={`${pages.length} page${pages.length === 1 ? "" : "s"} · live pipeline evidence`}
      >
        {loading ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : pages.length ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Page</TableHead>
                  <TableHead>Classification</TableHead>
                  <TableHead>Source & confidence</TableHead>
                  <TableHead>Group</TableHead>
                  <TableHead>Rotation</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pages.map((page) => (
                  <TableRow key={page.id}>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <a
                          href={documentImageUrl(page.image_url)}
                          target="_blank"
                          rel="noreferrer"
                          aria-label={`Open page ${page.page_number} image`}
                        >
                          <img
                            src={documentImageUrl(page.image_url)}
                            alt={`Page ${page.page_number} thumbnail from ${page.document_filename}`}
                            loading="lazy"
                            className="h-16 w-12 rounded-md border bg-muted object-cover"
                          />
                        </a>
                        <div className="min-w-0">
                          <p className="font-medium">Page {page.page_number}</p>
                          <p className="max-w-48 truncate text-xs text-muted-foreground">
                            {page.document_filename}
                          </p>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col items-start gap-1">
                        <StatusBadge status={humanise(page.page_type)} />
                        <span className="text-xs text-muted-foreground">
                          {page.review_status}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col items-start gap-1">
                        <Badge variant="outline">
                          {page.classification_source === "handler"
                            ? "Handler"
                            : "Pipeline"}
                        </Badge>
                        <span className="text-xs text-muted-foreground">
                          {humanise(page.extraction_method)} ·{" "}
                          {page.classification_confidence == null
                            ? "confidence unavailable"
                            : `${Math.round(page.classification_confidence * 100)}% confidence`}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {page.group_id ?? "Ungrouped"}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {page.rotation}°
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openCorrection(page)}
                        >
                          <PencilLineIcon data-icon="inline-start" />
                          Correct
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <FileTextIcon />
              </EmptyMedia>
              <EmptyTitle>No processed pages</EmptyTitle>
              <EmptyDescription>
                Upload and process a current repair invoice before reviewing
                page evidence.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </DataCard>

      {pages.length ? (
        <Alert>
          <FileCheck2Icon />
          <AlertTitle>
            {invoiceGroups.size} invoice unit
            {invoiceGroups.size === 1 ? "" : "s"} identified
          </AlertTitle>
          <AlertDescription>
            Invoice pages share a group identifier. Estimates, MOT history and
            unrelated pages remain separate document units.
          </AlertDescription>
        </Alert>
      ) : null}

      <Dialog
        open={Boolean(selectedPage)}
        onOpenChange={(open) => {
          if (!open && !saving) setSelectedPage(null)
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Correct page {selectedPage?.page_number}</DialogTitle>
            <DialogDescription>
              Save a handler classification, group or rotation override. Machine
              evidence is retained.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCorrection} className="flex flex-col gap-4">
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="page-correction-actor">Handler</FieldLabel>
                <Input
                  id="page-correction-actor"
                  value={draft.actor}
                  required
                  disabled={saving}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      actor: event.target.value,
                    }))
                  }
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="page-correction-type">
                  Classification
                </FieldLabel>
                <Select
                  value={draft.pageType}
                  disabled={saving}
                  onValueChange={(value) =>
                    setDraft((current) => ({
                      ...current,
                      pageType: value as DocumentPageType,
                    }))
                  }
                >
                  <SelectTrigger id="page-correction-type" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {PAGE_TYPES.map((pageType) => (
                        <SelectItem key={pageType} value={pageType}>
                          {humanise(pageType)}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field>
                  <FieldLabel htmlFor="page-correction-group">
                    Group identifier
                  </FieldLabel>
                  <Input
                    id="page-correction-group"
                    value={draft.groupId}
                    placeholder="Ungrouped"
                    disabled={saving}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        groupId: event.target.value,
                      }))
                    }
                  />
                  <FieldDescription>
                    Clear this field to remove the page from a group.
                  </FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="page-correction-rotation">
                    Rotation
                  </FieldLabel>
                  <Select
                    value={draft.rotation}
                    disabled={saving}
                    onValueChange={(value) =>
                      setDraft((current) => ({ ...current, rotation: value }))
                    }
                  >
                    <SelectTrigger
                      id="page-correction-rotation"
                      className="w-full"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {["0", "90", "180", "270"].map((rotation) => (
                          <SelectItem key={rotation} value={rotation}>
                            {rotation}°
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                </Field>
              </div>
              <Field data-invalid={Boolean(correctionError)}>
                <FieldLabel htmlFor="page-correction-reason">Reason</FieldLabel>
                <Textarea
                  id="page-correction-reason"
                  value={draft.reason}
                  minLength={3}
                  required
                  disabled={saving}
                  aria-invalid={Boolean(correctionError)}
                  placeholder="What did you verify in the source PDF?"
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      reason: event.target.value,
                    }))
                  }
                />
                <FieldDescription>
                  This reason is written to the append-only audit trail.
                </FieldDescription>
              </Field>
            </FieldGroup>

            {correctionError ? (
              <Alert variant="destructive">
                <AlertCircleIcon />
                <AlertTitle>Correction could not be saved</AlertTitle>
                <AlertDescription>{correctionError}</AlertDescription>
              </Alert>
            ) : null}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={saving}
                onClick={() => setSelectedPage(null)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={
                  saving ||
                  !draft.actor.trim() ||
                  draft.reason.trim().length < 3
                }
              >
                {saving ? (
                  <LoaderCircleIcon
                    data-icon="inline-start"
                    className="animate-spin"
                  />
                ) : (
                  <SaveIcon data-icon="inline-start" />
                )}
                {saving ? "Saving correction" : "Save correction"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
