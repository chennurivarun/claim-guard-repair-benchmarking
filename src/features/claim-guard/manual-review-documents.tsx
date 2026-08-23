import { useEffect, useState } from "react"
import { PlusIcon } from "lucide-react"
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
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import {
  addManualInvoiceLine,
  fetchClaimInvoices,
  getApiErrorMessage,
  type ClaimInvoiceSummary,
} from "@/lib/api"
import { DocumentBriefingButton } from "./document-briefing"
import {
  documentApiErrorMessage,
  fetchCaseDocuments,
  type UploadedDocument,
} from "./document-api"
import { DataCard, StatusBadge } from "./shared"

const HANDLER_ID = "pilot.handler"

const ITEM_KIND_OPTIONS = [
  { value: "part", label: "Part" },
  { value: "labour", label: "Labour" },
  { value: "paint", label: "Paint" },
  { value: "service", label: "Service" },
  { value: "disposal", label: "Disposal" },
  { value: "consumable", label: "Consumable" },
  { value: "unknown", label: "Other" },
] as const

interface ManualLineFormValues {
  description: string
  quantity: string
  unit: string
  lineTotalNet: string
  vatRate: string
  partNumber: string
  itemKind: string
}

const EMPTY_FORM: ManualLineFormValues = {
  description: "",
  quantity: "1",
  unit: "each",
  lineTotalNet: "",
  vatRate: "20",
  partNumber: "",
  itemKind: "part",
}

/**
 * Closes the manual review hub's "Manual line entry arrives with the next
 * backend update" gap: for each document the pipeline routed to manual
 * review, show the AI briefing plus a small form to add billable lines by
 * hand so they flow into mapping and comparison on the next run.
 */
export function ManualReviewDocumentsSection({
  caseReference,
  enabled,
}: {
  caseReference: string
  enabled: boolean
}) {
  const [documents, setDocuments] = useState<UploadedDocument[]>([])
  const [invoices, setInvoices] = useState<ClaimInvoiceSummary[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [activeDocument, setActiveDocument] = useState<UploadedDocument | null>(
    null
  )
  const [saving, setSaving] = useState(false)

  const loadData = (onSettled?: () => boolean) => {
    void Promise.all([
      fetchCaseDocuments(caseReference),
      fetchClaimInvoices(caseReference),
    ])
      .then(([documentRecords, invoiceRecords]) => {
        if (onSettled && !onSettled()) return
        setDocuments(documentRecords)
        setInvoices(invoiceRecords)
        setLoadError(null)
      })
      .catch((error: unknown) => {
        if (!onSettled || onSettled()) setLoadError(documentApiErrorMessage(error))
      })
  }

  useEffect(() => {
    let active = true
    loadData(() => active)
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseReference])

  const manualReviewDocuments = documents.filter(
    (document) => document.manual_review
  )
  const invoiceByDocumentId = new Map(
    invoices
      .filter((invoice) => invoice.document_id)
      .map((invoice) => [invoice.document_id as string, invoice])
  )

  const handleSubmit = async (
    invoice: ClaimInvoiceSummary,
    values: ManualLineFormValues
  ) => {
    setSaving(true)
    try {
      await addManualInvoiceLine(caseReference, invoice.id, {
        description: values.description.trim(),
        quantity: values.quantity ? Number(values.quantity) : undefined,
        unit: values.unit.trim() || undefined,
        lineTotalNet: Number(values.lineTotalNet),
        vatRate: values.vatRate ? Number(values.vatRate) : undefined,
        itemKind: values.itemKind,
        partNumber: values.partNumber.trim() || undefined,
        recordedBy: HANDLER_ID,
      })
      toast.success("Line added", {
        description: `${values.description} was added to ${invoice.document_filename}.`,
      })
      setActiveDocument(null)
      loadData()
    } catch (error) {
      toast.error("Could not add line", {
        description: getApiErrorMessage(error),
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <DataCard
        title="Manual review documents"
        description="Documents the pipeline could not benchmark automatically. Review the AI briefing, then add any billable lines by hand."
      >
        {loadError ? (
          <Alert variant="destructive">
            <AlertTitle>Could not load documents</AlertTitle>
            <AlertDescription>{loadError}</AlertDescription>
          </Alert>
        ) : null}
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Document</TableHead>
                <TableHead>Why it needs review</TableHead>
                <TableHead className="text-right">Status</TableHead>
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {manualReviewDocuments.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="py-8 text-center text-muted-foreground"
                  >
                    No documents currently require manual review.
                  </TableCell>
                </TableRow>
              ) : null}
              {manualReviewDocuments.map((document) => {
                const invoice = invoiceByDocumentId.get(document.id)
                return (
                  <TableRow key={document.id}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-1">
                        <span>{document.filename}</span>
                        <DocumentBriefingButton
                          filename={document.filename}
                          briefing={document.review_briefing}
                        />
                      </div>
                    </TableCell>
                    <TableCell className="max-w-sm text-muted-foreground">
                      {document.manual_review_reason ??
                        "Line-item information is unavailable."}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <StatusBadge status="MANUAL REVIEW" />
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        {invoice ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={!enabled}
                            onClick={() => setActiveDocument(document)}
                          >
                            <PlusIcon data-icon="inline-start" />
                            Add line manually
                          </Button>
                        ) : (
                          <Badge variant="outline">
                            Awaiting invoice record
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      </DataCard>
      <ManualLineDialog
        key={activeDocument?.id ?? "closed-manual-line-dialog"}
        document={activeDocument}
        invoice={
          activeDocument ? invoiceByDocumentId.get(activeDocument.id) ?? null : null
        }
        open={activeDocument !== null}
        onOpenChange={(open) => !open && setActiveDocument(null)}
        onSubmit={handleSubmit}
        saving={saving}
      />
    </>
  )
}

function ManualLineDialog({
  document,
  invoice,
  open,
  onOpenChange,
  onSubmit,
  saving,
}: {
  document: UploadedDocument | null
  invoice: ClaimInvoiceSummary | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (
    invoice: ClaimInvoiceSummary,
    values: ManualLineFormValues
  ) => Promise<void>
  saving: boolean
}) {
  const [values, setValues] = useState<ManualLineFormValues>(EMPTY_FORM)

  const lineTotalValue = Number(values.lineTotalNet)
  const invalid =
    !values.description.trim() ||
    !Number.isFinite(lineTotalValue) ||
    lineTotalValue <= 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add line manually</DialogTitle>
          <DialogDescription>
            {document?.filename} · recorded as a handler-approved line so it
            flows into mapping and comparison on the next run.
          </DialogDescription>
        </DialogHeader>

        <FieldGroup>
          <Field data-invalid={!values.description.trim()}>
            <FieldLabel htmlFor="manual-line-description">
              Description
            </FieldLabel>
            <Input
              id="manual-line-description"
              value={values.description}
              onChange={(event) =>
                setValues((current) => ({
                  ...current,
                  description: event.target.value,
                }))
              }
              aria-invalid={!values.description.trim()}
              aria-required="true"
            />
          </Field>
          <FieldGroup className="grid sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="manual-line-quantity">Quantity</FieldLabel>
              <Input
                id="manual-line-quantity"
                type="number"
                min="0"
                step="0.01"
                value={values.quantity}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    quantity: event.target.value,
                  }))
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="manual-line-unit">Unit</FieldLabel>
              <Input
                id="manual-line-unit"
                value={values.unit}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    unit: event.target.value,
                  }))
                }
              />
            </Field>
          </FieldGroup>
          <FieldGroup className="grid sm:grid-cols-2">
            <Field data-invalid={!Number.isFinite(lineTotalValue) || lineTotalValue <= 0}>
              <FieldLabel htmlFor="manual-line-total">
                Net total
              </FieldLabel>
              <Input
                id="manual-line-total"
                type="number"
                min="0.01"
                step="0.01"
                value={values.lineTotalNet}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    lineTotalNet: event.target.value,
                  }))
                }
                aria-invalid={!Number.isFinite(lineTotalValue) || lineTotalValue <= 0}
                aria-required="true"
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="manual-line-vat">VAT rate %</FieldLabel>
              <Input
                id="manual-line-vat"
                type="number"
                min="0"
                max="100"
                step="0.01"
                value={values.vatRate}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    vatRate: event.target.value,
                  }))
                }
              />
            </Field>
          </FieldGroup>
          <FieldGroup className="grid sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="manual-line-kind">Item kind</FieldLabel>
              <Select
                value={values.itemKind}
                onValueChange={(value) =>
                  setValues((current) => ({ ...current, itemKind: value }))
                }
              >
                <SelectTrigger id="manual-line-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ITEM_KIND_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel htmlFor="manual-line-part-number">
                Part number
              </FieldLabel>
              <Input
                id="manual-line-part-number"
                value={values.partNumber}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    partNumber: event.target.value,
                  }))
                }
              />
            </Field>
          </FieldGroup>
        </FieldGroup>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button
            type="button"
            disabled={invalid || saving || !invoice}
            onClick={() => invoice && void onSubmit(invoice, values)}
          >
            {saving ? "Adding…" : "Add line"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
