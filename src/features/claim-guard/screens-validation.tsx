import { useState, type FormEvent } from "react"
import {
  ArrowRightIcon,
  CalculatorIcon,
  CheckIcon,
  CheckCircle2Icon,
  EyeIcon,
  GitBranchIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
  ShieldCheckIcon,
  SplitIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
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
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
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
  getApiErrorMessage,
  type MappingDecisionAction,
  type MappingDecisionInput,
} from "@/lib/api"

import { DataCard, ScreenHeading, StatusBadge } from "./shared"
import { formatMoney } from "./format"
import {
  InvoiceSourceViewer,
  SourceReviewLayout,
} from "./invoice-source-viewer"
import type {
  CalculationCheck,
  ClaimWorkspace,
  InvoiceLine,
  OntologyBankItem,
} from "./types"

export function CalculationChecksScreen({
  workspace,
  onContinue,
}: {
  workspace: ClaimWorkspace
  onContinue: () => void
}) {
  const checks = workspace.checks ?? []
  const [selectedCheckId, setSelectedCheckId] = useState<string | null>(
    () =>
      sessionStorage.getItem("claimguard:selected-calculation-check") ??
      checks[0]?.id ??
      null
  )
  const [splitOpen, setSplitOpen] = useState(
    () => sessionStorage.getItem("claimguard:checks-split") === "open"
  )
  const selectedCheck =
    checks.find((check) => check.id === selectedCheckId) ?? null
  const passed = checks.filter((check) => check.status === "pass").length
  const notApplicable = checks.filter(
    (check) => check.status === "not_applicable"
  ).length
  const lineChecks = checks.filter(
    (check) => check.type === "LINE_MATH_MISMATCH"
  )
  const linePassed = lineChecks.filter(
    (check) => check.status === "pass"
  ).length
  const coverage = lineChecks.length
    ? Math.round((linePassed / lineChecks.length) * 100)
    : 0

  function setViewerOpen(open: boolean) {
    setSplitOpen(open)
    sessionStorage.setItem("claimguard:checks-split", open ? "open" : "closed")
  }

  function checkLabel(check: CalculationCheck) {
    return check.type.replaceAll("_", " ").replace("MISMATCH", "check")
  }

  const content = (
    <div className="space-y-6">
      <ScreenHeading
        compact={splitOpen}
        title="Calculation Checks"
        description="Deterministic arithmetic verifies line extensions, subtotals, VAT and the final invoice total."
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setViewerOpen(!splitOpen)}>
              <EyeIcon data-icon="inline-start" />
              {splitOpen ? "Hide invoice" : "View invoice"}
            </Button>
            <Button onClick={onContinue}>
              Review mappings
              <ArrowRightIcon data-icon="inline-end" />
            </Button>
          </div>
        }
      />

      <div
        className={
          splitOpen
            ? "grid gap-4 sm:grid-cols-2"
            : "grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
        }
      >
        <Card>
          <CardHeader>
            <CardDescription>Calculation checks</CardDescription>
            <CardTitle className="text-2xl tabular-nums">
              {passed} passed
            </CardTitle>
            {notApplicable > 0 && (
              <CardDescription>{notApplicable} not applicable</CardDescription>
            )}
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Taxable subtotal</CardDescription>
            <CardTitle className="text-2xl tabular-nums">
              {formatMoney(workspace.invoice.taxableNet)}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>VAT verified</CardDescription>
            <CardTitle className="text-2xl tabular-nums">
              {formatMoney(workspace.invoice.vat)}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Gross invoice</CardDescription>
            <CardTitle className="text-2xl tabular-nums">
              {formatMoney(workspace.invoice.gross)}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Alert>
        <CalculatorIcon />
        <AlertTitle>MOT excluded from VAT</AlertTitle>
        <AlertDescription>
          The {formatMoney(workspace.invoice.mot)} MOT charge is added after VAT
          and remains outside the negotiation VAT computation.
        </AlertDescription>
      </Alert>

      <DataCard
        title="Validation ledger"
        description="Expected values are derived from extracted net line totals."
      >
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Check</TableHead>
                <TableHead>Calculation</TableHead>
                <TableHead className="text-right">Expected</TableHead>
                <TableHead className="text-right">Extracted</TableHead>
                <TableHead className="text-right">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {checks.map((check) => (
                <TableRow
                  key={check.id}
                  tabIndex={0}
                  data-state={
                    selectedCheck?.id === check.id ? "selected" : undefined
                  }
                  onClick={() => {
                    setSelectedCheckId(check.id)
                    sessionStorage.setItem(
                      "claimguard:selected-calculation-check",
                      check.id
                    )
                    setViewerOpen(true)
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      setSelectedCheckId(check.id)
                      sessionStorage.setItem(
                        "claimguard:selected-calculation-check",
                        check.id
                      )
                      setViewerOpen(true)
                    }
                  }}
                >
                  <TableCell className="font-medium">
                    {checkLabel(check)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {check.explanation}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {check.expected == null ? "—" : formatMoney(check.expected)}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {check.observed == null ? "—" : formatMoney(check.observed)}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end">
                      <StatusBadge status={check.status} />
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {!checks.length && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="h-24 text-center text-muted-foreground"
                  >
                    No stored calculation findings are available yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </DataCard>

      <DataCard
        title="Line-extension coverage"
        description="Quantity × unit price verified for every priced line."
      >
        <div className="flex flex-col gap-4">
          <div className="flex items-end justify-between gap-4">
            <div>
              <p className="text-sm font-medium">
                {linePassed} of {lineChecks.length} lines verified
              </p>
              <p className="text-xs text-muted-foreground">
                No tolerance breach above £0.01 after currency rounding.
              </p>
            </div>
            <span className="text-sm font-semibold tabular-nums">
              {coverage}%
            </span>
          </div>
          <Progress
            value={coverage}
            aria-label={`${coverage}% of invoice line calculations verified`}
          />
        </div>
      </DataCard>
    </div>
  )

  return (
    <SourceReviewLayout
      open={splitOpen}
      onOpenChange={setViewerOpen}
      viewer={
        <InvoiceSourceViewer
          key={selectedCheck?.id ?? "checks"}
          caseReference={workspace.claim.id}
          documentId={workspace.invoice.documentId}
          pageNumbers={workspace.invoice.pageNumbers}
          sources={selectedCheck?.sources ?? []}
        />
      }
    >
      {content}
    </SourceReviewLayout>
  )
}

export interface MappingDialogSelection {
  line: InvoiceLine
  action: MappingDecisionAction
}

interface BundleComponentDraft {
  ontologyItemId: string
  allocatedNet: string
  quantity: string
  unit: string
}

const emptyBundleComponent = (): BundleComponentDraft => ({
  ontologyItemId: "",
  allocatedNet: "",
  quantity: "",
  unit: "",
})

function optionalNumber(value: string, label: string) {
  if (!value.trim()) return undefined
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error(`${label} must be a valid non-negative number.`)
  }
  return parsed
}

export function MappingDecisionDialog({
  selection,
  ontologyOptions,
  onOpenChange,
  onSubmit,
  saving,
}: {
  selection: MappingDialogSelection
  ontologyOptions: OntologyBankItem[]
  onOpenChange: (open: boolean) => void
  onSubmit: (
    line: InvoiceLine,
    input: Omit<MappingDecisionInput, "actor">
  ) => Promise<void>
  saving: boolean
}) {
  const { line, action } = selection
  const [rationale, setRationale] = useState("")
  const [ontologyItemId, setOntologyItemId] = useState(line.ontologyId ?? "")
  const [components, setComponents] = useState<BundleComponentDraft[]>(() => {
    if (line.bundleComponents && line.bundleComponents.length >= 2) {
      return line.bundleComponents.map((component) => ({
        ontologyItemId: component.ontology_item_id,
        allocatedNet: component.allocated_net ?? "",
        quantity: component.quantity ?? "",
        unit: component.unit ?? "",
      }))
    }
    return [emptyBundleComponent(), emptyBundleComponent()]
  })
  const [error, setError] = useState<string | null>(null)

  function updateComponent(
    index: number,
    update: Partial<BundleComponentDraft>
  ) {
    setComponents((current) =>
      current.map((component, componentIndex) =>
        componentIndex === index ? { ...component, ...update } : component
      )
    )
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    try {
      if (!rationale.trim()) throw new Error("A handler rationale is required.")
      if (action === "approve" && !line.ontologyId) {
        throw new Error(
          "This line has no candidate to approve; use Change or Bundle."
        )
      }
      if (action === "change" && !ontologyItemId.trim()) {
        throw new Error("Enter the replacement ontology item ID.")
      }

      const input: Omit<MappingDecisionInput, "actor"> = {
        decision: action,
        rationale: rationale.trim(),
      }
      if (action === "change") input.ontologyItemId = ontologyItemId.trim()
      if (action === "bundle") {
        if (components.length < 2)
          throw new Error("A bundle needs at least two components.")
        input.bundleComponents = components.map((component, index) => {
          if (!component.ontologyItemId.trim()) {
            throw new Error(`Component ${index + 1} needs an ontology item ID.`)
          }
          const allocatedNet = optionalNumber(
            component.allocatedNet,
            `Component ${index + 1} allocated net`
          )
          const quantity = optionalNumber(
            component.quantity,
            `Component ${index + 1} quantity`
          )
          if (allocatedNet === undefined && quantity === undefined) {
            throw new Error(
              `Component ${index + 1} needs an explicit net allocation or quantity.`
            )
          }
          if (quantity === 0) {
            throw new Error(
              `Component ${index + 1} quantity must be greater than zero.`
            )
          }
          return {
            ontologyItemId: component.ontologyItemId.trim(),
            allocatedNet,
            quantity,
            unit: component.unit.trim() || undefined,
          }
        })
      }

      await onSubmit(line, input)
      onOpenChange(false)
    } catch (submitError) {
      setError(getApiErrorMessage(submitError))
    }
  }

  const title =
    action === "approve"
      ? "Approve repair item link"
      : action === "change"
        ? "Change repair item"
        : action === "reject"
          ? "Reject match"
          : "Link bundled items"

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!saving || open) onOpenChange(open)
      }}
    >
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"
        showCloseButton={!saving}
      >
        <form className="contents" onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>
              {line.description} · source net {formatMoney(line.currentTotal)}.
              The source line remains unchanged.
            </DialogDescription>
          </DialogHeader>

          <FieldGroup>
            {action === "approve" && (
              <Field>
                <FieldLabel>Current repair item reference</FieldLabel>
                <Input value={line.ontologyId ?? "No candidate"} readOnly />
                <FieldDescription>
                  Approval confirms this repair item link only. Price evidence
                  is reviewed separately.
                </FieldDescription>
              </Field>
            )}

            {action === "change" && (
              <Field>
                <FieldLabel htmlFor="mapping-ontology-id">
                  Replacement repair item
                </FieldLabel>
                <select
                  id="mapping-ontology-id"
                  className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                  value={ontologyItemId}
                  onChange={(event) => setOntologyItemId(event.target.value)}
                  autoFocus
                >
                  <option value="">Choose a repair item</option>
                  {ontologyOptions.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} ({item.code})
                    </option>
                  ))}
                </select>
                <FieldDescription>
                  Choose from the active repair item library; no internal ID is
                  required.
                </FieldDescription>
              </Field>
            )}

            {action === "bundle" && (
              <FieldSet>
                <FieldLegend>Bundle components</FieldLegend>
                <FieldDescription>
                  Allocate every component net so the total equals{" "}
                  {formatMoney(line.currentTotal)}, or enter quantities only to
                  keep the bundle non-comparable. ClaimGuard never guesses the
                  split.
                </FieldDescription>
                <div className="flex flex-col gap-3">
                  {components.map((component, index) => (
                    <Card key={index} size="sm">
                      <CardHeader>
                        <CardTitle>Component {index + 1}</CardTitle>
                        <CardDescription>
                          Handler-declared repair item
                        </CardDescription>
                        <CardAction>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            disabled={components.length <= 2 || saving}
                            onClick={() =>
                              setComponents((current) =>
                                current.filter(
                                  (_, componentIndex) =>
                                    componentIndex !== index
                                )
                              )
                            }
                          >
                            <Trash2Icon />
                            <span className="sr-only">
                              Remove component {index + 1}
                            </span>
                          </Button>
                        </CardAction>
                      </CardHeader>
                      <CardContent>
                        <FieldGroup className="grid gap-3 sm:grid-cols-2">
                          <Field className="sm:col-span-2">
                            <FieldLabel htmlFor={`bundle-item-${index}`}>
                              Repair item reference
                            </FieldLabel>
                            <select
                              id={`bundle-item-${index}`}
                              className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                              value={component.ontologyItemId}
                              onChange={(event) =>
                                updateComponent(index, {
                                  ontologyItemId: event.target.value,
                                })
                              }
                            >
                              <option value="">Choose a repair item</option>
                              {ontologyOptions.map((item) => (
                                <option key={item.id} value={item.id}>
                                  {item.name} ({item.code})
                                </option>
                              ))}
                            </select>
                          </Field>
                          <Field>
                            <FieldLabel htmlFor={`bundle-net-${index}`}>
                              Allocated net (£)
                            </FieldLabel>
                            <Input
                              id={`bundle-net-${index}`}
                              type="number"
                              min="0"
                              step="0.01"
                              value={component.allocatedNet}
                              onChange={(event) =>
                                updateComponent(index, {
                                  allocatedNet: event.target.value,
                                })
                              }
                              placeholder="Optional"
                            />
                          </Field>
                          <Field>
                            <FieldLabel htmlFor={`bundle-quantity-${index}`}>
                              Quantity
                            </FieldLabel>
                            <Input
                              id={`bundle-quantity-${index}`}
                              type="number"
                              min="0.0001"
                              step="any"
                              value={component.quantity}
                              onChange={(event) =>
                                updateComponent(index, {
                                  quantity: event.target.value,
                                })
                              }
                              placeholder="Optional"
                            />
                          </Field>
                          <Field className="sm:col-span-2">
                            <FieldLabel htmlFor={`bundle-unit-${index}`}>
                              Unit
                            </FieldLabel>
                            <Input
                              id={`bundle-unit-${index}`}
                              value={component.unit}
                              onChange={(event) =>
                                updateComponent(index, {
                                  unit: event.target.value,
                                })
                              }
                              placeholder="each, hour, litre…"
                            />
                          </Field>
                        </FieldGroup>
                      </CardContent>
                    </Card>
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={saving}
                    onClick={() =>
                      setComponents((current) => [
                        ...current,
                        emptyBundleComponent(),
                      ])
                    }
                  >
                    <PlusIcon data-icon="inline-start" />
                    Add component
                  </Button>
                </div>
              </FieldSet>
            )}

            <Field data-invalid={Boolean(error)}>
              <FieldLabel htmlFor="mapping-rationale">
                Handler rationale
              </FieldLabel>
              <Textarea
                id="mapping-rationale"
                value={rationale}
                onChange={(event) => setRationale(event.target.value)}
                placeholder="What did you verify, and why is this decision appropriate?"
                aria-invalid={Boolean(error)}
              />
              <FieldError>{error}</FieldError>
            </Field>
          </FieldGroup>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={saving}
              onClick={() => onOpenChange(false)}
            >
              <XIcon data-icon="inline-start" />
              Cancel
            </Button>
            <Button
              type="submit"
              variant={action === "reject" ? "destructive" : "default"}
              disabled={saving}
            >
              {saving ? (
                <LoaderCircleIcon
                  className="animate-spin"
                  data-icon="inline-start"
                />
              ) : (
                <CheckIcon data-icon="inline-start" />
              )}
              Save decision
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function MappingRows({
  lines,
  enabled,
  savingLineId,
  onSelect,
}: {
  lines: InvoiceLine[]
  enabled: boolean
  savingLineId: string | null
  onSelect: (line: InvoiceLine, action: MappingDecisionAction) => void
}) {
  return (
    <div className="overflow-x-auto">
      <Table className="min-w-[840px] table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead className="w-[18%]">Invoice item</TableHead>
            <TableHead className="w-[18%]">Standard repair item</TableHead>
            <TableHead className="w-[7%]">Link</TableHead>
            <TableHead className="w-[25%]">Why this match</TableHead>
            <TableHead className="w-[12%] text-right">Review status</TableHead>
            <TableHead className="w-[20%] text-right">Decision</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {lines.map((line) => (
            <TableRow key={line.id}>
              <TableCell className="break-words whitespace-normal align-top">
                <div className="min-w-0">
                  <p className="font-medium">{line.description}</p>
                  <p className="text-xs text-muted-foreground">
                    {line.kind} · {line.quantity} {line.unit}
                    {line.partNumber ? ` · ${line.partNumber}` : ""}
                  </p>
                </div>
              </TableCell>
              <TableCell className="break-words whitespace-normal align-top">
                <div className="min-w-0">
                  <p className="font-medium">
                    {line.ontologyName ?? "No approved candidate"}
                  </p>
                  {line.isBundled ? (
                    <p className="text-xs text-muted-foreground">
                      {line.bundleComponents?.length ?? 0} linked repair items
                    </p>
                  ) : !line.ontologyId ? (
                    <p className="text-xs text-muted-foreground">
                      Select a repair item to continue
                    </p>
                  ) : null}
                </div>
              </TableCell>
              <TableCell>
                <Badge variant="outline">
                  {line.isBundled ? "1:n" : "1:1"}
                </Badge>
              </TableCell>
              <TableCell className="align-top break-words whitespace-normal text-muted-foreground">
                <p className="line-clamp-2">{line.rationale}</p>
                {line.rationale.length > 140 ? (
                  <details className="mt-1 text-xs">
                    <summary className="cursor-pointer font-medium text-foreground">
                      Full explanation
                    </summary>
                    <p className="mt-2 leading-relaxed">{line.rationale}</p>
                  </details>
                ) : null}
              </TableCell>
              <TableCell>
                <div className="flex justify-end">
                  <StatusBadge
                    status={
                      line.mappingStatus === "MATCH" ||
                      (line.mappingConfidence ?? 0) > 95
                        ? "Approved"
                        : ["REVIEW", "PENDING", "PROVISIONAL"].some(
                              (status) =>
                                (
                                  line.mappingReviewStatus ??
                                  line.mappingStatus
                                )
                                  .toUpperCase()
                                  .includes(status)
                            )
                          ? "Awaiting review"
                          : (line.mappingReviewStatus ?? line.mappingStatus)
                    }
                  />
                </div>
              </TableCell>
              <TableCell className="whitespace-normal align-top">
                <div className="flex min-w-0 flex-wrap justify-end gap-1">
                  <Button
                    size="xs"
                    disabled={
                      !enabled ||
                      line.mappingStatus === "MATCH" ||
                      (line.mappingConfidence ?? 0) > 95 ||
                      savingLineId === line.id
                    }
                    onClick={() =>
                      onSelect(line, line.ontologyId ? "approve" : "change")
                    }
                  >
                    {line.ontologyId ? (
                      <CheckIcon data-icon="inline-start" />
                    ) : (
                      <PencilIcon data-icon="inline-start" />
                    )}
                    {line.mappingStatus === "MATCH" ||
                    (line.mappingConfidence ?? 0) > 95
                      ? "Accepted"
                      : !line.ontologyId
                        ? "Select item"
                      : "Approve"}
                  </Button>
                  <Button
                    size="xs"
                    variant="outline"
                    disabled={!enabled || savingLineId === line.id}
                    onClick={() => onSelect(line, "change")}
                  >
                    <PencilIcon data-icon="inline-start" />
                    Change
                  </Button>
                  <Button
                    size="icon-xs"
                    variant="outline"
                    aria-label="Link as bundle"
                    title="Link as bundle"
                    disabled={!enabled || savingLineId === line.id}
                    onClick={() => onSelect(line, "bundle")}
                  >
                    <SplitIcon />
                  </Button>
                  <Button
                    size="icon-xs"
                    variant="destructive"
                    aria-label="Reject match"
                    title="Reject match"
                    disabled={!enabled || savingLineId === line.id}
                    onClick={() => onSelect(line, "reject")}
                  >
                    <XIcon />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

export function OntologyMappingScreen({
  workspace,
  onContinue,
  onOpenLibrary,
  mappingEnabled,
  savingLineId,
  onMappingDecision,
}: {
  workspace: ClaimWorkspace
  onContinue: () => void
  onOpenLibrary: () => void
  mappingEnabled: boolean
  savingLineId: string | null
  onMappingDecision: (
    line: InvoiceLine,
    input: Omit<MappingDecisionInput, "actor">
  ) => Promise<void>
}) {
  const [selection, setSelection] = useState<MappingDialogSelection | null>(
    null
  )
  const activeLines = workspace.lines.filter(
    (line) => line.mappingStatus !== "EXCLUDED"
  )
  const matched = activeLines.filter(
    (line) =>
      line.mappingStatus === "MATCH" || (line.mappingConfidence ?? 0) > 95
  )
  const provisional = activeLines.filter(
    (line) =>
      line.mappingStatus !== "MATCH" && (line.mappingConfidence ?? 0) <= 95
  )
  return (
    <>
      <ScreenHeading
        title="Repair item matching"
        description="Check how each invoice line has been linked to a standard repair item."
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={onOpenLibrary}>
              Repair item library
            </Button>
            <Button onClick={onContinue}>
              Compare prices
              <ArrowRightIcon data-icon="inline-end" />
            </Button>
          </div>
        }
      />

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardDescription>Approved matches</CardDescription>
            <CardTitle className="flex items-center gap-2 text-2xl">
              <CheckCircle2Icon className="size-5 text-success" aria-hidden />
              {matched.length}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Ready for price comparison
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Awaiting review</CardDescription>
            <CardTitle className="text-2xl tabular-nums">
              {provisional.length}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            A handler decision is still required
          </CardContent>
        </Card>
      </div>

      <Alert>
        <GitBranchIcon />
        <AlertTitle>Bundle prices are never guessed</AlertTitle>
        <AlertDescription>
          One invoice line can link to several repair items. If the price cannot
          be divided safely, it is sent for human review.
        </AlertDescription>
      </Alert>

      {!mappingEnabled && (
        <Alert>
          <ShieldCheckIcon />
          <AlertTitle>Mapping decisions are read-only</AlertTitle>
          <AlertDescription>
            This case is read-only. Mapping decisions require a connected
            FastAPI workspace and an unfinalised case; demo mode never simulates
            an approval.
          </AlertDescription>
        </Alert>
      )}

      <DataCard
        title="Review matches"
        description={`${matched.length} approved · ${provisional.length} awaiting review`}
        action={<Badge variant="outline">Audit trail retained</Badge>}
      >
        <MappingRows
          lines={activeLines}
          enabled={mappingEnabled}
          savingLineId={savingLineId}
          onSelect={(line, action) => setSelection({ line, action })}
        />
      </DataCard>

      <Alert>
        <ShieldCheckIcon />
        <AlertTitle>Every change remains auditable</AlertTitle>
        <AlertDescription>
          Approving, changing or rejecting a match creates a new decision
          record. The original suggestion remains available in the audit trail.
        </AlertDescription>
      </Alert>

      {selection && (
        <MappingDecisionDialog
          key={`${selection.line.id}-${selection.action}`}
          selection={selection}
          ontologyOptions={workspace.ontologyBank?.items ?? []}
          saving={savingLineId === selection.line.id}
          onOpenChange={(open) => {
            if (!open) setSelection(null)
          }}
          onSubmit={onMappingDecision}
        />
      )}
    </>
  )
}
