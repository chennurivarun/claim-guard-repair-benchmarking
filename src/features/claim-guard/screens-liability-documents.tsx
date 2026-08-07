import { useState } from "react"
import {
  ArrowRightIcon,
  CheckIcon,
  CheckCircle2Icon,
  EyeIcon,
  FileCheck2Icon,
  FileSpreadsheetIcon,
  FileTextIcon,
  LockKeyholeIcon,
  PencilLineIcon,
  RefreshCwIcon,
  ShieldAlertIcon,
  Undo2Icon,
  UploadCloudIcon,
  XIcon,
} from "lucide-react"
import { toast } from "sonner"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
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
import { Checkbox } from "@/components/ui/checkbox"
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
import { Separator } from "@/components/ui/separator"
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
  consistencyChecks,
  evidenceRows,
  pageClassifications,
} from "./demo-data"
import { formatMoney } from "./format"
import {
  DocumentPagesWorkflow,
  UploadProcessingWorkflow,
} from "./screens-document-workflow"
import { DataCard, ScreenHeading, StatusBadge } from "./shared"
import {
  InvoiceSourceViewer,
  SourceReviewLayout,
} from "./invoice-source-viewer"
import type { ClaimWorkspace, InvoiceLine, LiabilityStatus } from "./types"
import type { CalculationSourceReference } from "./types"
import { LIABILITY_STATUSES } from "./types"

export function ClaimLiabilityScreen({
  workspace,
  status,
  confirmed,
  onStatusChange,
  onConfirm,
  onContinue,
  confirming,
}: {
  workspace: ClaimWorkspace
  status: LiabilityStatus
  confirmed: boolean
  onStatusChange: (status: LiabilityStatus) => void
  onConfirm: (decision: {
    rationale: string
    splitLiabilityPercentage?: number
  }) => void
  onContinue: () => void
  confirming: boolean
}) {
  const [rationale, setRationale] = useState(
    workspace.liability.rationale ?? ""
  )
  const [splitPercentage, setSplitPercentage] = useState(
    workspace.liability.splitLiabilityPercentage?.toString() ?? ""
  )

  const canIssue =
    confirmed && (status === "ADMITTED" || status === "SPLIT LIABILITY")
  const splitValue = Number(splitPercentage)
  const splitInvalid =
    status === "SPLIT LIABILITY" &&
    (!splitPercentage.trim() ||
      !Number.isFinite(splitValue) ||
      splitValue < 0 ||
      splitValue > 100)
  const decisionInvalid = !rationale.trim() || splitInvalid

  return (
    <>
      <ScreenHeading
        title="Claim & Liability"
        description="Record responsibility and claim consistency; analysis remains draft until the issuance gate is satisfied."
        action={
          <StatusBadge status={confirmed ? `${status} · confirmed` : status} />
        }
      />

      <Alert>
        <ShieldAlertIcon />
        <AlertTitle>The invoice never decides fault</AlertTitle>
        <AlertDescription>
          Automated checks may summarise evidence and identify contradictions. A
          claims handler must make and confirm the final liability decision.
        </AlertDescription>
      </Alert>

      <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(340px,0.75fr)]">
        <DataCard
          title="Claim record"
          description="Parties, vehicles and accident facts held for this case."
        >
          <FieldGroup className="grid md:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="claim-number">Claim number</FieldLabel>
              <Input id="claim-number" value={workspace.claim.id} readOnly />
            </Field>
            <Field>
              <FieldLabel htmlFor="policy-number">Policy number</FieldLabel>
              <Input
                id="policy-number"
                value={workspace.claim.policyNumber}
                readOnly
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="accident-date">Accident date</FieldLabel>
              <Input
                id="accident-date"
                value={workspace.claim.accidentDate}
                readOnly
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="accident-location">
                Accident location
              </FieldLabel>
              <Input
                id="accident-location"
                value={workspace.claim.accidentLocation}
                readOnly
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="paying-insurer">Paying insurer</FieldLabel>
              <Input
                id="paying-insurer"
                value={workspace.claim.payingInsurer}
                readOnly
              />
              <FieldDescription>
                {workspace.claim.insuredDriver}
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="claiming-party">
                Claiming insurer / party
              </FieldLabel>
              <Input
                id="claiming-party"
                value={workspace.claim.claimingParty}
                readOnly
              />
              <FieldDescription>
                {workspace.claim.thirdPartyDriver}
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="insured-vehicle">Insured vehicle</FieldLabel>
              <Input
                id="insured-vehicle"
                value={`${workspace.claim.insuredVehicle} · ${workspace.claim.insuredVrm}`}
                readOnly
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="third-party-vehicle">
                Third-party vehicle
              </FieldLabel>
              <Input
                id="third-party-vehicle"
                value={`${workspace.claim.thirdPartyVehicle} · ${workspace.claim.thirdPartyVrm}`}
                readOnly
              />
            </Field>
            <Field className="md:col-span-2">
              <FieldLabel htmlFor="accident-description">
                Accident description
              </FieldLabel>
              <Textarea
                id="accident-description"
                value={workspace.claim.accidentDescription}
                readOnly
              />
            </Field>
            <Field className="md:col-span-2">
              <FieldLabel htmlFor="damage-description">
                Damage description
              </FieldLabel>
              <Textarea
                id="damage-description"
                value={workspace.claim.damageDescription}
                readOnly
              />
            </Field>
          </FieldGroup>
        </DataCard>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle>Handler decision</CardTitle>
            <CardDescription>
              This decision gates issuance. Draft invoice analysis remains
              available for every status.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="liability-status">
                  Liability status
                </FieldLabel>
                <Select
                  value={status}
                  onValueChange={(value) =>
                    onStatusChange(value as LiabilityStatus)
                  }
                >
                  <SelectTrigger id="liability-status" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {LIABILITY_STATUSES.map((value) => (
                        <SelectItem key={value} value={value}>
                          {value}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <FieldDescription>
                  ADMITTED or SPLIT LIABILITY may unlock issuance after handler
                  confirmation.
                </FieldDescription>
              </Field>
              {status === "SPLIT LIABILITY" ? (
                <Field data-invalid={splitInvalid}>
                  <FieldLabel htmlFor="split-liability-percentage">
                    Insured liability percentage
                  </FieldLabel>
                  <Input
                    id="split-liability-percentage"
                    type="number"
                    min="0"
                    max="100"
                    step="1"
                    value={splitPercentage}
                    onChange={(event) => setSplitPercentage(event.target.value)}
                    aria-required="true"
                    aria-invalid={splitInvalid}
                  />
                  <FieldDescription>
                    Required for split-liability decisions.
                  </FieldDescription>
                </Field>
              ) : null}
              <Field data-invalid={!rationale.trim()}>
                <FieldLabel htmlFor="liability-rationale">
                  Handler rationale
                </FieldLabel>
                <Textarea
                  id="liability-rationale"
                  value={rationale}
                  onChange={(event) => setRationale(event.target.value)}
                  placeholder="Record the evidence supporting this status"
                  aria-required="true"
                  aria-invalid={!rationale.trim()}
                />
                <FieldDescription>
                  Stored with the human decision and immutable audit event.
                </FieldDescription>
              </Field>
              <Field orientation="horizontal">
                <Checkbox id="authority" checked={confirmed} disabled />
                <div>
                  <FieldLabel htmlFor="authority">
                    Handler decision recorded
                  </FieldLabel>
                  <FieldDescription>
                    Original evidence and later edits remain in the audit log.
                  </FieldDescription>
                </div>
              </Field>
            </FieldGroup>

            <Separator />

            <div className="flex flex-col gap-3 text-sm">
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Invoice vehicle</span>
                <span className="font-medium">{workspace.invoice.vrm}</span>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Invoice total</span>
                <span className="font-medium tabular-nums">
                  {formatMoney(workspace.invoice.gross)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">Draft analysis</span>
                <StatusBadge status="AVAILABLE" />
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-muted-foreground">
                  Challenge issuance
                </span>
                <StatusBadge status={canIssue ? "UNLOCKED" : "LOCKED"} />
              </div>
            </div>
          </CardContent>
          <CardFooter className="flex-col items-stretch gap-2">
            {!confirmed ? (
              <>
                <Button
                  disabled={decisionInvalid || confirming}
                  onClick={() =>
                    onConfirm({
                      rationale: rationale.trim(),
                      splitLiabilityPercentage:
                        status === "SPLIT LIABILITY" ? splitValue : undefined,
                    })
                  }
                >
                  <CheckCircle2Icon data-icon="inline-start" />
                  {confirming ? "Saving decision..." : "Confirm liability"}
                </Button>
                <Button
                  variant="outline"
                  onClick={onContinue}
                  disabled={confirming}
                >
                  Continue draft analysis
                  <ArrowRightIcon data-icon="inline-end" />
                </Button>
              </>
            ) : (
              <Button onClick={onContinue}>
                Continue to documents
                <ArrowRightIcon data-icon="inline-end" />
              </Button>
            )}
            {!canIssue ? (
              <p className="text-center text-xs text-muted-foreground">
                Draft analysis remains available; challenge issuance is gated
                for {status.toLowerCase()} claims.
              </p>
            ) : null}
          </CardFooter>
        </Card>
      </div>

      <div className="grid min-w-0 gap-6 2xl:grid-cols-2">
        <DataCard
          title="Consistency checks"
          description="Claim facts checked against invoice 91283."
        >
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Check</TableHead>
                  <TableHead>Finding</TableHead>
                  <TableHead className="text-right">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {consistencyChecks.map(([check, finding, result]) => (
                  <TableRow key={check}>
                    <TableCell className="font-medium">{check}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {finding}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <StatusBadge status={result} />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </DataCard>

        <DataCard
          title="Evidence register"
          description="Evidence supports review; it does not automate fault."
        >
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Evidence</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Finding</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {evidenceRows.map(([evidence, date, review, finding]) => (
                  <TableRow key={evidence}>
                    <TableCell className="font-medium">{evidence}</TableCell>
                    <TableCell>{date}</TableCell>
                    <TableCell>
                      <StatusBadge status={review} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {finding}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </DataCard>
      </div>
    </>
  )
}

function UploadCard({
  title,
  description,
  status,
  detail,
  icon: Icon,
  action,
}: {
  title: string
  description: string
  status: string
  detail: string
  icon: typeof FileTextIcon
  action: string
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
      <CardFooter>
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            toast.success(`${title} ready`, { description: detail })
          }
        >
          <RefreshCwIcon data-icon="inline-start" />
          {action}
        </Button>
      </CardFooter>
    </Card>
  )
}

export function LegacyUploadProcessingScreen({
  onContinue,
}: {
  onContinue: () => void
}) {
  return (
    <>
      <ScreenHeading
        title="Upload & Processing"
        description="The current repair invoice is required. Active ontology and previous-invoice banks can be reused."
        action={
          <Button onClick={onContinue}>
            Review pages
            <ArrowRightIcon data-icon="inline-end" />
          </Button>
        }
      />

      <Alert>
        <LockKeyholeIcon />
        <AlertTitle>Liability gate passed</AlertTitle>
        <AlertDescription>
          Handler-confirmed ADMITTED liability unlocked quantum processing for
          this claim.
        </AlertDescription>
      </Alert>

      <div className="grid gap-6 lg:grid-cols-3">
        <UploadCard
          title="Current repair invoice"
          description="Required for this claim"
          status="UPLOADED"
          detail="1643919_doc_16439191.pdf.pdf · 2 pages"
          icon={FileTextIcon}
          action="Replace PDF"
        />
        <UploadCard
          title="Ontology / reference bank"
          description="Optional pilot or admin import"
          status="ACTIVE V1.0"
          detail="72 ontology items · active bank reused"
          icon={FileSpreadsheetIcon}
          action="Use active bank"
        />
        <UploadCard
          title="Previous invoice bank"
          description="Optional supporting evidence"
          status="READY"
          detail="191 previous repair & service lines"
          icon={UploadCloudIcon}
          action="Use active bank"
        />
      </div>

      <DataCard
        title="Processing run"
        description="Native extraction is attempted before OCR or vision."
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
              {[
                [
                  "File intake",
                  "SHA-256 + MIME validation",
                  "No duplicate file detected",
                  "PASS",
                ],
                [
                  "Page scan",
                  "Native text and coordinates",
                  "2 of 2 pages classified",
                  "PASS",
                ],
                [
                  "Table extraction",
                  "Native PDF table",
                  "18 invoice lines extracted",
                  "PASS",
                ],
                [
                  "Calculation validation",
                  "Deterministic Python rules",
                  "6 of 6 checks passed",
                  "PASS",
                ],
                [
                  "Ontology mapping",
                  "Candidate retrieval + structured mapping",
                  "14 matched · 4 provisional",
                  "REVIEW",
                ],
              ].map(([stage, method, result, status]) => (
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

export function LegacyDocumentPagesScreen({
  onContinue,
}: {
  onContinue: () => void
}) {
  return (
    <>
      <ScreenHeading
        title="Document Pages"
        description="Every page is classified before any invoice unit is created."
        action={
          <Button onClick={onContinue}>
            Review extraction
            <ArrowRightIcon data-icon="inline-end" />
          </Button>
        }
      />

      <DataCard
        title="1643919_doc_16439191.pdf.pdf"
        description="2 pages · native text available"
      >
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Page</TableHead>
                <TableHead>Classification</TableHead>
                <TableHead>Extraction path</TableHead>
                <TableHead>Finding</TableHead>
                <TableHead className="text-right">Confidence</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pageClassifications.map((page) => (
                <TableRow key={page.page}>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <span className="flex size-9 items-center justify-center rounded-md bg-muted">
                        <FileTextIcon className="size-5" aria-hidden />
                      </span>
                      <span className="font-medium">Page {page.page}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={page.type} />
                  </TableCell>
                  <TableCell>{page.extraction}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {page.note}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {page.confidence}%
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </DataCard>

      <Alert>
        <FileCheck2Icon />
        <AlertTitle>One invoice unit identified</AlertTitle>
        <AlertDescription>
          Both pages reference invoice 91283 and were grouped together.
          Estimates, MOT history and unrelated pages would remain separate
          document units.
        </AlertDescription>
      </Alert>
    </>
  )
}

export const UploadProcessingScreen = UploadProcessingWorkflow
export const DocumentPagesScreen = DocumentPagesWorkflow

export function ExtractedInvoiceScreen({
  workspace,
  onEdit,
  onDecision,
  savingLineId,
  onContinue,
}: {
  workspace: ClaimWorkspace
  onEdit: (line: InvoiceLine) => void
  onDecision: (
    line: InvoiceLine,
    decision: "approved" | "rejected" | "undo",
    reason?: string
  ) => Promise<void>
  savingLineId?: string | null
  onContinue: () => void
}) {
  const [selectedLineId, setSelectedLineId] = useState<string | null>(() =>
    sessionStorage.getItem("claimguard:selected-invoice-line")
  )
  const [splitOpen, setSplitOpen] = useState(
    () => sessionStorage.getItem("claimguard:invoice-split") === "open"
  )
  const [rejectingLine, setRejectingLine] = useState<InvoiceLine | null>(null)
  const [rejectReason, setRejectReason] = useState("")
  const selectedLine =
    workspace.lines.find((line) => line.id === selectedLineId) ?? null
  const unresolved = workspace.lines.filter(
    (line) => line.requiresExtractionReview
  )

  function setViewerOpen(open: boolean) {
    setSplitOpen(open)
    sessionStorage.setItem("claimguard:invoice-split", open ? "open" : "closed")
  }

  function selectLine(line: InvoiceLine) {
    setSelectedLineId(line.id)
    sessionStorage.setItem("claimguard:selected-invoice-line", line.id)
    if (line.requiresExtractionReview) setViewerOpen(true)
  }

  const sources: CalculationSourceReference[] = selectedLine?.source?.regions
    .row
    ? [
        {
          pageId: selectedLine.source.pageId,
          pageNumber: selectedLine.source.pageNumber,
          label: selectedLine.description,
          bbox: selectedLine.source.regions.row,
          precision: selectedLine.source.precision,
        },
      ]
    : []

  const content = (
    <div className="space-y-6">
      <ScreenHeading
        compact={splitOpen}
        title={`Extracted Invoice ${workspace.invoice.number}`}
        description="Review the raw extraction and correct any field before ontology mapping."
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setViewerOpen(!splitOpen)}>
              <EyeIcon data-icon="inline-start" />
              {splitOpen ? "Hide invoice" : "View invoice"}
            </Button>
            <Button onClick={onContinue} disabled={unresolved.length > 0}>
              Run calculation checks
              <ArrowRightIcon data-icon="inline-end" />
            </Button>
          </div>
        }
      />

      {unresolved.length > 0 && (
        <Alert>
          <ShieldAlertIcon />
          <AlertTitle>
            {unresolved.length} low-confidence{" "}
            {unresolved.length === 1 ? "item requires" : "items require"} review
          </AlertTitle>
          <AlertDescription>
            Select each amber item and Accept, Edit or Reject it before
            calculation checks.
          </AlertDescription>
        </Alert>
      )}

      <div
        className={
          splitOpen
            ? "grid gap-6"
            : "grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.6fr)]"
        }
      >
        <DataCard
          title={workspace.invoice.garage}
          description={workspace.invoice.address}
        >
          <div className="overflow-x-auto">
            <Table>
              <TableBody>
                {[
                  [
                    "Invoice number",
                    workspace.invoice.number,
                    "Invoice date",
                    workspace.invoice.date,
                  ],
                  [
                    "Vehicle",
                    workspace.invoice.vehicle,
                    "Registration",
                    workspace.invoice.vrm,
                  ],
                  [
                    "Vehicle category",
                    workspace.invoice.vehicleCategory?.groupRange
                      ? `${workspace.invoice.vehicleCategory.groupRange} · ${workspace.invoice.vehicleCategory.groupCategory}`
                      : "Unclassified — manual review",
                    "Lookup match",
                    workspace.invoice.vehicleCategory?.matchStatus
                      ?.replaceAll("_", " ") ?? "manual review",
                  ],
                  [
                    "Mileage",
                    workspace.invoice.mileage.toLocaleString("en-GB"),
                    "Page range",
                    workspace.invoice.pageNumbers?.join("–") || "—",
                  ],
                ].map(([a, b, c, d]) => (
                  <TableRow key={a}>
                    <TableCell className="text-muted-foreground">{a}</TableCell>
                    <TableCell className="font-medium">{b}</TableCell>
                    <TableCell className="text-muted-foreground">{c}</TableCell>
                    <TableCell className="font-medium">{d}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </DataCard>

        <DataCard
          title="Invoice totals"
          description="MOT is non-VAT and shown separately."
        >
          <div className="flex flex-col gap-3 text-sm">
            {[
              ["Parts net", workspace.invoice.partsNet],
              ["Labour net", workspace.invoice.labourNet],
              ["Taxable subtotal", workspace.invoice.taxableNet],
              ["VAT", workspace.invoice.vat],
              ["MOT · non-VAT", workspace.invoice.mot],
            ].map(([label, value]) => (
              <div
                key={String(label)}
                className="flex items-center justify-between gap-4"
              >
                <span className="text-muted-foreground">{label}</span>
                <span className="font-medium tabular-nums">
                  {formatMoney(value as number)}
                </span>
              </div>
            ))}
            <Separator />
            <div className="flex items-center justify-between gap-4">
              <span className="font-medium">Gross invoice total</span>
              <span className="text-lg font-semibold tabular-nums">
                {formatMoney(workspace.invoice.gross)}
              </span>
            </div>
          </div>
        </DataCard>
      </div>

      <DataCard
        title="Extracted line items"
        description={`${workspace.lines.length} quantity-adjusted invoice lines · amounts shown net`}
      >
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Description</TableHead>
                <TableHead>Part no.</TableHead>
                <TableHead>Type</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead>Unit</TableHead>
                <TableHead className="text-right">Unit price</TableHead>
                <TableHead className="text-right">Net total</TableHead>
                <TableHead className="text-right">VAT</TableHead>
                <TableHead className="text-right">Confidence</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-10">
                  <span className="sr-only">Edit</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {workspace.lines.map((line) => (
                <TableRow
                  key={line.id}
                  tabIndex={0}
                  aria-selected={selectedLine?.id === line.id}
                  className={
                    line.extractionReviewStatus === "rejected"
                      ? "opacity-55"
                      : undefined
                  }
                  data-state={
                    selectedLine?.id === line.id ? "selected" : undefined
                  }
                  onClick={() => selectLine(line)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ")
                      selectLine(line)
                  }}
                >
                  <TableCell className="font-medium">
                    {line.description}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {line.partNumber ?? "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{line.kind}</Badge>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {line.quantity}
                  </TableCell>
                  <TableCell>{line.unit}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(line.unitPrice)}
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {formatMoney(line.currentTotal)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {line.vatRate}%
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {line.extractionConfidence > 95 ? (
                      <Badge variant="success">
                        <CheckIcon aria-hidden />
                        Approved
                      </Badge>
                    ) : (
                      <Badge
                        variant={
                          line.requiresExtractionReview
                            ? "secondary"
                            : "outline"
                        }
                      >
                        {line.extractionConfidence}%
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusBadge
                      status={
                        line.extractionConfidence > 95 &&
                        !["rejected", "corrected"].includes(
                          line.extractionReviewStatus ?? ""
                        )
                          ? "approved"
                          : (line.extractionReviewStatus ?? "pending")
                      }
                    />
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={(event) => {
                        event.stopPropagation()
                        onEdit(line)
                      }}
                      aria-label={`Edit ${line.description}`}
                    >
                      <PencilLineIcon />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </DataCard>

      {selectedLine &&
        (selectedLine.requiresExtractionReview ||
          ["approved", "rejected"].includes(
            selectedLine.extractionReviewStatus ?? ""
          )) && (
          <DataCard
            title={`Review · ${selectedLine.description}`}
            description="Verify the highlighted invoice row, then record your decision."
          >
            <div className="flex flex-wrap items-center gap-2">
              {selectedLine.requiresExtractionReview && (
                <>
                  <Button
                    size="sm"
                    disabled={savingLineId === selectedLine.id}
                    onClick={() => void onDecision(selectedLine, "approved")}
                  >
                    <CheckIcon data-icon="inline-start" />
                    Accept
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onEdit(selectedLine)}
                  >
                    <PencilLineIcon data-icon="inline-start" />
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => setRejectingLine(selectedLine)}
                  >
                    <XIcon data-icon="inline-start" />
                    Reject
                  </Button>
                </>
              )}
              {["approved", "rejected"].includes(
                selectedLine.extractionReviewStatus ?? ""
              ) && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={savingLineId === selectedLine.id}
                  onClick={() => void onDecision(selectedLine, "undo")}
                >
                  <Undo2Icon data-icon="inline-start" />
                  Undo decision
                </Button>
              )}
              {selectedLine.extractionReviewStatus === "rejected" && (
                <span className="text-sm text-muted-foreground">
                  Excluded from calculations and mapping; retained in the audit
                  trail.
                </span>
              )}
            </div>
          </DataCard>
        )}
    </div>
  )

  return (
    <>
      <SourceReviewLayout
        open={splitOpen}
        onOpenChange={setViewerOpen}
        viewer={
          <InvoiceSourceViewer
            key={selectedLine?.id ?? "invoice"}
            caseReference={workspace.claim.id}
            documentId={workspace.invoice.documentId}
            pageNumbers={workspace.invoice.pageNumbers}
            sources={sources}
          />
        }
      >
        {content}
      </SourceReviewLayout>

      <AlertDialog
        open={Boolean(rejectingLine)}
        onOpenChange={(open) => {
          if (!open) {
            setRejectingLine(null)
            setRejectReason("")
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reject this extracted line?</AlertDialogTitle>
            <AlertDialogDescription>
              The line stays in the audit trail but is excluded from
              calculations and mapping.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <Field>
            <FieldLabel htmlFor="extraction-reject-reason">Reason</FieldLabel>
            <Textarea
              id="extraction-reject-reason"
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              placeholder="Briefly explain why this extraction is wrong"
            />
          </Field>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={
                !rejectReason.trim() || savingLineId === rejectingLine?.id
              }
              onClick={() => {
                if (!rejectingLine || !rejectReason.trim()) return
                void onDecision(rejectingLine, "rejected", rejectReason.trim())
                setRejectingLine(null)
                setRejectReason("")
              }}
            >
              Reject line
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
