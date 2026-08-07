import { useState } from "react"
import { CheckCircle2Icon, SaveIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"

import { formatMoney } from "./format"
import { ConfidenceCell, StatusBadge } from "./shared"
import type { InvoiceLine } from "./types"

export interface LineCorrectionValues {
  description: string
  quantity: number
  unitPrice: number
  reason: string
}

export interface SettlementValues {
  agreedAmountNet: number
  lines: Array<{ lineItemId: string; agreedAmountNet: number }>
}

export function LineCorrectionSheet({
  line,
  open,
  onOpenChange,
  onSave,
  saving,
}: {
  line: InvoiceLine | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSave: (values: LineCorrectionValues) => void
  saving: boolean
}) {
  const [description, setDescription] = useState(line?.description ?? "")
  const [quantity, setQuantity] = useState(line ? String(line.quantity) : "")
  const [unitPrice, setUnitPrice] = useState(
    line ? line.unitPrice.toFixed(2) : ""
  )
  const [reason, setReason] = useState("")

  const quantityValue = Number(quantity)
  const unitPriceValue = Number(unitPrice)
  const invalid =
    !line ||
    !description.trim() ||
    !reason.trim() ||
    !Number.isFinite(quantityValue) ||
    quantityValue <= 0 ||
    !Number.isFinite(unitPriceValue) ||
    unitPriceValue < 0

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>{line?.description ?? "Line review"}</SheetTitle>
          <SheetDescription>
            Review extraction, mapping and price evidence. A correction creates
            a new audited record.
          </SheetDescription>
        </SheetHeader>

        {line ? (
          <div className="flex flex-col gap-6 px-4 pb-6">
            <Alert>
              <CheckCircle2Icon />
              <AlertTitle>Original extraction retained</AlertTitle>
              <AlertDescription>
                Saving a correction never overwrites the raw PDF extraction or
                original model suggestion.
              </AlertDescription>
            </Alert>

            <FieldGroup>
              <Field data-invalid={!description.trim()}>
                <FieldLabel htmlFor="line-description">
                  Invoice description
                </FieldLabel>
                <Textarea
                  id="line-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  aria-invalid={!description.trim()}
                />
              </Field>
              <FieldGroup className="grid sm:grid-cols-2">
                <Field
                  data-invalid={
                    !Number.isFinite(quantityValue) || quantityValue <= 0
                  }
                >
                  <FieldLabel htmlFor="line-quantity">Quantity</FieldLabel>
                  <Input
                    id="line-quantity"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={quantity}
                    onChange={(event) => setQuantity(event.target.value)}
                    aria-invalid={
                      !Number.isFinite(quantityValue) || quantityValue <= 0
                    }
                  />
                </Field>
                <Field
                  data-invalid={
                    !Number.isFinite(unitPriceValue) || unitPriceValue < 0
                  }
                >
                  <FieldLabel htmlFor="line-unit-price">
                    Unit price · net
                  </FieldLabel>
                  <Input
                    id="line-unit-price"
                    type="number"
                    min="0"
                    step="0.01"
                    value={unitPrice}
                    onChange={(event) => setUnitPrice(event.target.value)}
                    aria-invalid={
                      !Number.isFinite(unitPriceValue) || unitPriceValue < 0
                    }
                  />
                </Field>
              </FieldGroup>
              <Field data-invalid={!reason.trim()}>
                <FieldLabel htmlFor="correction-reason">
                  Correction reason
                </FieldLabel>
                <Input
                  id="correction-reason"
                  placeholder="Required when a value changes"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  aria-required="true"
                  aria-invalid={!reason.trim()}
                />
                <FieldDescription>
                  Reason is stored with handler, timestamp and policy version.
                </FieldDescription>
              </Field>
            </FieldGroup>

            <Separator />

            <div>
              <h3 className="text-sm font-medium">Mapping & evidence</h3>
              <Table className="mt-2">
                <TableBody>
                  <TableRow>
                    <TableCell className="text-muted-foreground">
                      Ontology item
                    </TableCell>
                    <TableCell className="text-right font-medium">
                      {line.ontologyId ?? "No approved item"}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="text-muted-foreground">
                      Current net line
                    </TableCell>
                    <TableCell className="text-right font-medium tabular-nums">
                      {formatMoney(line.currentTotal)}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="text-muted-foreground">
                      Ontology price
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMoney(line.ontologyTotal)}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="text-muted-foreground">
                      Historic median
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMoney(line.historicalMedian)}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="text-muted-foreground">
                      Challenge Price
                    </TableCell>
                    <TableCell className="text-right font-medium tabular-nums">
                      {formatMoney(line.recommended)}
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="text-muted-foreground">
                      Mapping confidence
                    </TableCell>
                    <TableCell className="text-right">
                      <ConfidenceCell value={line.mappingConfidence} />
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="text-muted-foreground">
                      Evidence confidence
                    </TableCell>
                    <TableCell className="text-right">
                      <ConfidenceCell value={line.evidenceConfidence} />
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="text-muted-foreground">
                      Comparison state
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <StatusBadge status={line.comparisonStatus} />
                      </div>
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>

            <div>
              <h3 className="text-sm font-medium">Decision rationale</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {line.rationale}
              </p>
            </div>
          </div>
        ) : null}

        <SheetFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button
            disabled={invalid || saving}
            onClick={() =>
              onSave({
                description: description.trim(),
                quantity: quantityValue,
                unitPrice: unitPriceValue,
                reason: reason.trim(),
              })
            }
          >
            <SaveIcon data-icon="inline-start" />
            {saving ? "Saving correction..." : "Save correction"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

export function SettlementDialog({
  open,
  onOpenChange,
  onSave,
  lines,
  saving,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSave: (values: SettlementValues) => void
  lines: InvoiceLine[]
  saving: boolean
}) {
  const [amount, setAmount] = useState("")
  const [lineBreakdown, setLineBreakdown] = useState(false)
  const [lineAmounts, setLineAmounts] = useState<Record<string, string>>({})

  const amountValue = Number(amount)
  const amountInvalid = !Number.isFinite(amountValue) || amountValue <= 0
  const lineValuesInvalid = Object.values(lineAmounts).some(
    (value) =>
      value !== "" && (!Number.isFinite(Number(value)) || Number(value) < 0)
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Capture settlement</DialogTitle>
          <DialogDescription>
            The invoice-level settlement is required. A line-level allocation is
            optional.
          </DialogDescription>
        </DialogHeader>

        <FieldGroup>
          <Field data-invalid={open && amountInvalid}>
            <FieldLabel htmlFor="settlement-amount">
              Final invoice settlement · net
            </FieldLabel>
            <Input
              id="settlement-amount"
              type="number"
              min="0.01"
              step="0.01"
              placeholder="546.51"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              aria-required="true"
              aria-invalid={open && amountInvalid}
            />
            <FieldDescription>
              Required · gross and VAT effects are derived separately.
            </FieldDescription>
          </Field>

          <Field orientation="horizontal" data-disabled={lines.length === 0}>
            <Checkbox
              id="line-breakdown"
              checked={lineBreakdown}
              onCheckedChange={(value) => setLineBreakdown(value === true)}
              disabled={lines.length === 0}
            />
            <div>
              <FieldLabel htmlFor="line-breakdown">
                Add optional line settlement breakdown
              </FieldLabel>
              <FieldDescription>
                Useful gold-standard evidence, but not required from handlers.
              </FieldDescription>
            </div>
          </Field>

          {lineBreakdown ? (
            <FieldGroup className="grid sm:grid-cols-2">
              {lines.map((line) => {
                const value = lineAmounts[line.id] ?? ""
                const valueInvalid =
                  value !== "" &&
                  (!Number.isFinite(Number(value)) || Number(value) < 0)
                return (
                  <Field key={line.id} data-invalid={valueInvalid}>
                    <FieldLabel htmlFor={`settle-${line.id}`}>
                      {line.description}
                    </FieldLabel>
                    <Input
                      id={`settle-${line.id}`}
                      type="number"
                      min="0"
                      step="0.01"
                      placeholder={
                        line.recommended?.toFixed(2) ??
                        line.currentTotal.toFixed(2)
                      }
                      value={value}
                      onChange={(event) =>
                        setLineAmounts((current) => ({
                          ...current,
                          [line.id]: event.target.value,
                        }))
                      }
                      aria-invalid={valueInvalid}
                    />
                  </Field>
                )
              })}
            </FieldGroup>
          ) : null}
        </FieldGroup>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button
            disabled={amountInvalid || lineValuesInvalid || saving}
            onClick={() =>
              onSave({
                agreedAmountNet: amountValue,
                lines: lineBreakdown
                  ? lines.flatMap((line) => {
                      const value = lineAmounts[line.id]
                      return value === undefined || value === ""
                        ? []
                        : [
                            {
                              lineItemId: line.id,
                              agreedAmountNet: Number(value),
                            },
                          ]
                    })
                  : [],
              })
            }
          >
            {saving ? "Saving settlement..." : "Save settlement"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
