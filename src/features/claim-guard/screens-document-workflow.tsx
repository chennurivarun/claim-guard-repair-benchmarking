import { useEffect, useState } from "react"
import type { FormEvent } from "react"
import {
  AlertCircleIcon,
  ArrowRightIcon,
  FileCheck2Icon,
  FileTextIcon,
  LoaderCircleIcon,
  PencilLineIcon,
  RefreshCwIcon,
  SaveIcon,
} from "lucide-react"
import { toast } from "sonner"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
} from "./document-api"
import type { DocumentPageRecord, DocumentPageType } from "./document-api"
import { fetchEngineerAssessments } from "@/lib/api"
import { DataCard, ScreenHeading, StatusBadge } from "./shared"

function humanise(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase())
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
  caseReference,
  documentId,
  invoiceId,
}: {
  onContinue: () => void
  caseReference: string
  documentId?: string
  invoiceId?: string
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
    void Promise.all([
      fetchDocumentPages(caseReference),
      fetchEngineerAssessments(caseReference),
    ])
      .then(([allPages, assessments]) => {
        const pairedDocumentIds = new Set(
          assessments
            .filter((a) => a.pair_status === "paired")
            .filter((a) => a.paired_invoice_id === invoiceId)
            .map((a) => a.document_id)
        )
        const records = documentId
          ? allPages.filter(
              (p) =>
                p.document_id === documentId ||
                pairedDocumentIds.has(p.document_id)
            )
          : allPages
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
  }, [caseReference, documentId, invoiceId])

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
      setPages(
        (await fetchDocumentPages(caseReference)).filter(
          (p) => !documentId || p.document_id === documentId
        )
      )
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
