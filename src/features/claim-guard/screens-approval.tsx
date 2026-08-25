import { useState } from "react"
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  CheckCircle2Icon,
  CheckIcon,
  DownloadIcon,
  EyeIcon,
  FileCheck2Icon,
  FileTextIcon,
  InfoIcon,
  LockKeyholeIcon,
  ScaleIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
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

import { formatMoney } from "./format"
import { isMappingApproved } from "./mapping-rules"
import {
  ChallengeDecisionDialog,
  LineEvidenceSheet,
  type ResearchFormValues,
} from "./screens-challenge-admin"
import type { ClaimWorkspace, InvoiceLine, LiabilityStatus } from "./types"
import { LIABILITY_STATUSES } from "./types"
import type { MappingDecisionInput } from "@/lib/api"

function LiabilityConfirmationPanel({
  workspace,
  status,
  confirmed,
  confirming,
  canIssue,
  onStatusChange,
  onConfirm,
}: {
  workspace: ClaimWorkspace
  status: LiabilityStatus
  confirmed: boolean
  confirming: boolean
  canIssue: boolean
  onStatusChange: (status: LiabilityStatus) => void
  onConfirm: (decision: {
    rationale: string
    splitLiabilityPercentage?: number
  }) => void
}) {
  const [rationale, setRationale] = useState(
    workspace.liability.rationale ?? ""
  )
  const [splitPercentage, setSplitPercentage] = useState(
    workspace.liability.splitLiabilityPercentage?.toString() ?? ""
  )
  const splitValue = Number(splitPercentage)
  const splitInvalid =
    status === "SPLIT LIABILITY" &&
    (!splitPercentage.trim() ||
      !Number.isFinite(splitValue) ||
      splitValue < 0 ||
      splitValue > 100)
  const canConfirm = rationale.trim().length > 0 && !splitInvalid

  if (confirmed) {
    return (
      <div className="flex items-center gap-3">
        <CheckCircle2Icon
          className={canIssue ? "text-success" : "text-muted-foreground"}
          aria-hidden
        />
        <div>
          <p className="text-sm font-medium">Liability: {status}</p>
          <p className="text-xs text-muted-foreground">
            {canIssue
              ? "Handler decision permits challenge issuance"
              : "ADMITTED or SPLIT LIABILITY is required for issuance"}
          </p>
        </div>
      </div>
    )
  }

  return (
    <Card className="border-warning/40">
      <CardContent className="p-4">
        <div className="mb-3 flex items-center gap-2">
          <LockKeyholeIcon className="text-warning" aria-hidden />
          <p className="text-sm font-medium">
            Confirm liability to allow challenge issuance
          </p>
        </div>
        <FieldGroup className="gap-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="approval-liability-status">
                Liability status
              </FieldLabel>
              <Select
                value={status}
                onValueChange={(value) =>
                  onStatusChange(value as LiabilityStatus)
                }
              >
                <SelectTrigger
                  id="approval-liability-status"
                  size="sm"
                  className="w-full"
                >
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
            </Field>
            {status === "SPLIT LIABILITY" ? (
              <Field data-invalid={splitInvalid}>
                <FieldLabel htmlFor="approval-split-percentage">
                  Insured liability percentage
                </FieldLabel>
                <Input
                  id="approval-split-percentage"
                  type="number"
                  min="0"
                  max="100"
                  value={splitPercentage}
                  onChange={(event) => setSplitPercentage(event.target.value)}
                />
              </Field>
            ) : null}
          </div>
          <Field data-invalid={!rationale.trim()}>
            <FieldLabel htmlFor="approval-liability-rationale">
              Handler rationale
            </FieldLabel>
            <Textarea
              id="approval-liability-rationale"
              value={rationale}
              onChange={(event) => setRationale(event.target.value)}
              rows={2}
            />
            <FieldDescription>
              Saved with the immutable audit record.
            </FieldDescription>
          </Field>
          <div>
            <Button
              size="sm"
              disabled={confirming || !canConfirm}
              onClick={() =>
                onConfirm({
                  rationale: rationale.trim(),
                  splitLiabilityPercentage:
                    status === "SPLIT LIABILITY" ? splitValue : undefined,
                })
              }
            >
              <CheckIcon data-icon="inline-start" />
              {confirming ? "Saving decision..." : "Confirm liability"}
            </Button>
            {!canConfirm && !confirming ? (
              <p className="mt-2 text-xs text-muted-foreground">
                Enter a handler rationale
                {status === "SPLIT LIABILITY"
                  ? " and a valid split percentage (0-100)"
                  : ""}{" "}
                to confirm.
              </p>
            ) : null}
          </div>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}

export function ApprovalScreen({
  workspace,
  p90ThresholdPct,
  canIssue,
  comparisonReady,
  finalised,
  processing,
  enabled,
  caseUnresolvedChallenges,
  pendingInvoiceLabel,
  liabilityStatus,
  liabilityConfirmed,
  liabilityConfirming,
  onLiabilityStatusChange,
  onConfirmLiability,
  onDecision,
  onFinalise,
  onSettlement,
  onDownload,
  onBackToFindings,
  onReviewPendingInvoice,
  onMappingDecision,
  mappingSavingLineId,
  onProposeNewItem,
  researchSaving,
}: {
  workspace: ClaimWorkspace
  p90ThresholdPct: number
  canIssue: boolean
  comparisonReady: boolean
  finalised: boolean
  processing: boolean
  enabled: boolean
  caseUnresolvedChallenges: number
  pendingInvoiceLabel: string | null
  liabilityStatus: LiabilityStatus
  liabilityConfirmed: boolean
  liabilityConfirming: boolean
  onLiabilityStatusChange: (status: LiabilityStatus) => void
  onConfirmLiability: (decision: {
    rationale: string
    splitLiabilityPercentage?: number
  }) => void
  onDecision: (
    line: InvoiceLine,
    decision: {
      approved: boolean
      rationale: string
      challengePriceNet?: number
    }
  ) => Promise<void>
  onFinalise: () => void
  onSettlement: () => void
  onDownload: (format: "docx" | "pdf") => void
  onBackToFindings: () => void
  onReviewPendingInvoice?: () => void
  onMappingDecision?: (
    line: InvoiceLine,
    input: Omit<MappingDecisionInput, "actor">
  ) => Promise<void>
  mappingSavingLineId?: string | null
  onProposeNewItem?: (line: InvoiceLine, values: ResearchFormValues) => Promise<void>
  researchSaving?: boolean
}) {
  const [evidenceLine, setEvidenceLine] = useState<InvoiceLine | null>(null)
  const [decisionLine, setDecisionLine] = useState<InvoiceLine | null>(null)
  const [decisionMode, setDecisionMode] = useState<
    "approve" | "reject" | "edit" | null
  >(null)
  const challenged = workspace.lines.filter((line) => line.challenge > 0)
  const unresolved = challenged.filter(
    (line) =>
      !["approved", "rejected"].includes(line.challengeStatus ?? "review")
  )
  const pendingMappings = challenged.filter(
    (line) => !isMappingApproved(line)
  )
  const reviewed = challenged.length - unresolved.length
  const canFinalise =
    enabled &&
    canIssue &&
    comparisonReady &&
    pendingMappings.length === 0 &&
    unresolved.length === 0 &&
    caseUnresolvedChallenges === 0

  return (
    <>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Approve challenge
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {pendingMappings.length
              ? "Approve the challenged repair item matches before generating the challenge package."
              : caseUnresolvedChallenges
                ? "Review every uploaded invoice before generating the combined challenge package."
                : "All findings are reviewed. Confirm the figures and generate the challenge package."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            variant={
              unresolved.length || pendingMappings.length
                ? "warning"
                : "success"
            }
          >
            {reviewed} of {challenged.length}
          </Badge>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            {pendingMappings.length
              ? "mapping approval needed"
              : `${reviewed} reviewed`}
          </span>
        </div>
      </div>

      {pendingMappings.length ? (
        <Alert>
          <InfoIcon />
          <AlertTitle>Repair item matches still need approval</AlertTitle>
          <AlertDescription>
            {pendingMappings.length} challenged line
            {pendingMappings.length === 1 ? " is" : "s are"} still provisional.
            Approve the repair item match before recording or issuing a
            challenge decision.
          </AlertDescription>
        </Alert>
      ) : null}

      {unresolved.length && !pendingMappings.length ? (
        <Alert>
          <InfoIcon />
          <AlertTitle>Review findings first</AlertTitle>
          <AlertDescription className="flex items-center justify-between gap-4">
            <span>
              {unresolved.length} finding
              {unresolved.length === 1 ? " still needs" : "s still need"} a
              handler decision.
            </span>
            <Button variant="outline" size="sm" onClick={onBackToFindings}>
              <ArrowLeftIcon data-icon="inline-start" />
              Back to findings
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {!unresolved.length &&
      caseUnresolvedChallenges > 0 &&
      onReviewPendingInvoice ? (
        <Alert>
          <InfoIcon />
          <AlertTitle>Another invoice still needs review</AlertTitle>
          <AlertDescription className="flex items-center justify-between gap-4">
            <span>
              {caseUnresolvedChallenges} finding
              {caseUnresolvedChallenges === 1 ? "" : "s"} remain across the
              uploaded invoices.
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={onReviewPendingInvoice}
            >
              Review invoice {pendingInvoiceLabel}
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      <LiabilityConfirmationPanel
        workspace={workspace}
        status={liabilityStatus}
        confirmed={liabilityConfirmed}
        confirming={liabilityConfirming}
        canIssue={canIssue}
        onStatusChange={onLiabilityStatusChange}
        onConfirm={onConfirmLiability}
      />

      <section className="grid gap-5 border-y py-5 sm:grid-cols-3 xl:grid-cols-6">
        {[
          [
            "Proposed payable net",
            formatMoney(workspace.summary.challengePrice),
            "After the challenge amount",
          ],
          ["Original net", formatMoney(workspace.invoice.netIncludingMot), ""],
          [
            "Challenge amount",
            formatMoney(workspace.summary.challengeAmount),
            "",
          ],
          ["VAT impact", formatMoney(workspace.summary.vatImpact), ""],
          ["Gross cash effect", formatMoney(workspace.summary.grossEffect), ""],
          ["MOT", formatMoney(workspace.invoice.mot), "Outside VAT"],
        ].map(([label, value, hint], index) => (
          <div key={label} className={index ? "border-l pl-5" : undefined}>
            <p className="text-xs text-muted-foreground">{label}</p>
            <p
              className={
                index === 2
                  ? "mt-1 text-lg font-semibold text-destructive tabular-nums"
                  : index === 0
                    ? "mt-1 text-3xl font-semibold tracking-tight tabular-nums"
                    : "mt-1 text-lg font-semibold tabular-nums"
              }
            >
              {value}
            </p>
            {hint ? (
              <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
            ) : null}
          </div>
        ))}
      </section>

      <p className="text-xs text-muted-foreground">
        The negotiation letter uses net figures; VAT and MOT are shown for
        context.
      </p>

      <div className="flex items-center gap-3 border-y py-4">
        <FileCheck2Icon className="text-success" aria-hidden />
        <div>
          <p className="text-sm font-medium">
            Policy {workspace.versions?.policy ?? "v1.4"}
          </p>
          <p className="text-xs text-muted-foreground">
            50% in-house P90 · 30% previous claims · 20% verified external
          </p>
        </div>
      </div>

      <section>
        <h2 className="mb-3 text-sm font-semibold">Challenge findings</h2>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead className="text-right">Current net</TableHead>
                <TableHead className="text-right">Supported net</TableHead>
                <TableHead className="text-right">Challenge amount</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Decision</TableHead>
                <TableHead className="text-right">Evidence</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {challenged.map((line) => {
                const resolved =
                  line.challengeStatus === "approved" ||
                  line.challengeStatus === "rejected"
                const mappingApproved = !pendingMappings.includes(line)
                return (
                  <TableRow key={line.id}>
                    <TableCell className="font-medium">
                      {line.description}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMoney(line.currentTotal)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMoney(line.recommended)}
                    </TableCell>
                    <TableCell className="text-right font-medium text-destructive tabular-nums">
                      {formatMoney(line.challenge)}
                    </TableCell>
                    <TableCell>
                      <span
                        className={
                          line.challengeStatus === "approved"
                            ? "inline-flex items-center gap-1 text-xs text-success"
                            : line.challengeStatus === "rejected"
                              ? "inline-flex items-center gap-1 text-xs text-muted-foreground"
                              : "text-xs text-muted-foreground"
                        }
                      >
                        {line.challengeStatus === "approved" ? (
                          <CheckCircle2Icon aria-hidden />
                        ) : null}
                        {line.challengeStatus === "approved"
                          ? "Reviewed"
                          : line.challengeStatus === "rejected"
                            ? "Rejected"
                            : !mappingApproved
                              ? "Provisional mapping"
                              : "Awaiting decision"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        {resolved ? (
                          <span className="text-xs text-muted-foreground">
                            {line.challengeStatus === "approved"
                              ? "Approved"
                              : "Rejected"}
                          </span>
                        ) : !mappingApproved ? (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled
                            title="Approve repair item match first"
                          >
                            Approve repair item match first
                          </Button>
                        ) : (
                          <>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={!enabled || finalised || processing}
                              onClick={() => {
                                setDecisionLine(line)
                                setDecisionMode("approve")
                              }}
                            >
                              Approve
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={!enabled || finalised || processing}
                              onClick={() => {
                                setDecisionLine(line)
                                setDecisionMode("reject")
                              }}
                            >
                              Reject
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setEvidenceLine(line)}
                        >
                          <EyeIcon data-icon="inline-start" />
                          View evidence
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold">What will be generated</h2>
        <div className="flex flex-col gap-3 text-sm">
          <div className="grid gap-2 sm:grid-cols-[10rem_1fr]">
            <span className="flex items-center gap-2 font-medium">
              <FileTextIcon aria-hidden />
              Challenge letter PDF
            </span>
            <span className="text-muted-foreground">
              Professional negotiation letter with approved challenge figures
              and rationale.
            </span>
          </div>
          <div className="grid gap-2 sm:grid-cols-[10rem_1fr]">
            <span className="flex items-center gap-2 font-medium">
              <FileCheck2Icon aria-hidden />
              Evidence appendix
            </span>
            <span className="text-muted-foreground">
              Supporting evidence pack for the challenged line items.
            </span>
          </div>
        </div>
      </section>

      <Separator />
      <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-col gap-2 text-xs text-muted-foreground">
          <span className="flex items-center gap-2">
            <InfoIcon className="text-primary" aria-hidden />
            Settlement can be recorded after the package has been issued.
          </span>
          <span className="flex items-center gap-2">
            <InfoIcon className="text-primary" aria-hidden />
            Only approved positive variances are included; cheaper lines do not
            offset the challenge.
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {finalised ? (
            <>
              <Button variant="outline" onClick={() => onDownload("docx")}>
                <DownloadIcon data-icon="inline-start" />
                DOCX
              </Button>
              <Button variant="outline" onClick={() => onDownload("pdf")}>
                <FileTextIcon data-icon="inline-start" />
                PDF
              </Button>
              <Button variant="outline" onClick={onSettlement}>
                Capture settlement
              </Button>
            </>
          ) : (
            <Button variant="outline" onClick={onBackToFindings}>
              Back to findings
            </Button>
          )}
          <Button
            disabled={finalised || processing || !canFinalise}
            onClick={onFinalise}
          >
            <ScaleIcon data-icon="inline-start" />
            {finalised
              ? "Package generated"
              : processing
                ? "Generating..."
                : pendingMappings.length
                  ? "Approve repair item matches first"
                  : caseUnresolvedChallenges
                    ? "Review other invoices first"
                    : unresolved.length
                      ? "Review decisions first"
                      : "Generate challenge package"}
            <ArrowRightIcon data-icon="inline-end" />
          </Button>
        </div>
      </div>

      <LineEvidenceSheet
        line={evidenceLine}
        p90ThresholdPct={p90ThresholdPct}
        onClose={() => setEvidenceLine(null)}
        ontologyOptions={workspace.ontologyBank?.items ?? []}
        mappingSaving={mappingSavingLineId === evidenceLine?.id}
        onMappingDecision={onMappingDecision}
        researchSaving={researchSaving}
        onProposeNewItem={onProposeNewItem}
      />
      <ChallengeDecisionDialog
        key={`${decisionLine?.id ?? "closed"}-${decisionMode ?? "none"}`}
        line={decisionLine}
        mode={decisionMode}
        saving={processing}
        onClose={() => {
          setDecisionLine(null)
          setDecisionMode(null)
        }}
        onSubmit={async (decision) => {
          if (!decisionLine) return
          await onDecision(decisionLine, decision)
          setDecisionLine(null)
          setDecisionMode(null)
        }}
      />
    </>
  )
}
