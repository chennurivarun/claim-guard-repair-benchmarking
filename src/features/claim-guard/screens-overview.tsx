import { useState } from "react"
import {
  ArrowRightIcon,
  Building2Icon,
  CalendarDaysIcon,
  CarFrontIcon,
  CheckIcon,
  ChevronDownIcon,
  ClipboardListIcon,
  FileTextIcon,
  InfoIcon,
  LockKeyholeIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
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
import { Textarea } from "@/components/ui/textarea"

import { formatMoney } from "./format"
import { isMappingApproved } from "./mapping-rules"
import type { ClaimWorkspace, LiabilityStatus } from "./types"
import { LIABILITY_STATUSES } from "./types"

export function OverviewScreen({
  workspace,
  status,
  confirmed,
  onStatusChange,
  onConfirm,
  onReviewFindings,
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
  onReviewFindings: () => void
  confirming: boolean
}) {
  const [rationale, setRationale] = useState(
    workspace.liability.rationale ?? ""
  )
  const [splitPercentage, setSplitPercentage] = useState(
    workspace.liability.splitLiabilityPercentage?.toString() ?? ""
  )
  const challenged = workspace.lines.filter((line) => line.challenge > 0)
  const unresolved = challenged.filter(
    (line) =>
      !["approved", "rejected"].includes(line.challengeStatus ?? "review")
  )
  const provisionalChallengeMappings = challenged.filter(
    (line) => !isMappingApproved(line)
  )
  const splitValue = Number(splitPercentage)
  const splitInvalid =
    status === "SPLIT LIABILITY" &&
    (!splitPercentage.trim() ||
      !Number.isFinite(splitValue) ||
      splitValue < 0 ||
      splitValue > 100)
  const canConfirm = rationale.trim().length > 0 && !splitInvalid
  const date = new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date())
  const progress = [
    [
      "Liability confirmed",
      confirmed ? status.replace(" LIABILITY", "") : "Action needed",
    ],
    ["Documents processed", "Complete"],
    ["Findings ready", "Complete"],
    ["Challenge awaiting approval", "Your decision needed"],
  ]

  return (
    <>
      <div className="flex items-start justify-between gap-6">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            Case overview
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Your case is ready for challenge approval. Review the{" "}
            {challenged.length} challenged invoice lines and decide.
          </p>
        </div>
        <div className="hidden items-center gap-2 text-sm text-muted-foreground sm:flex">
          <span>{date}</span>
          <CalendarDaysIcon aria-hidden />
        </div>
      </div>

      <ol className="grid gap-4 py-2 lg:grid-cols-4" aria-label="Case progress">
        {progress.map(([label, detail], index) => (
          <li key={label} className="flex min-w-0 items-start gap-3">
            <span
              className={
                index < 3
                  ? "flex size-8 shrink-0 items-center justify-center rounded-full bg-success text-success-foreground"
                  : "flex size-8 shrink-0 items-center justify-center rounded-full border"
              }
            >
              {index < 3 ? (
                <CheckIcon aria-hidden />
              ) : (
                <span className="text-sm font-medium">4</span>
              )}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-3">
                <p className="text-sm font-medium">{label}</p>
                {index < progress.length - 1 ? (
                  <Separator className="hidden flex-1 xl:block" />
                ) : null}
              </div>
              <p
                className={
                  index < 3
                    ? "mt-1 text-xs text-success"
                    : "mt-1 text-xs text-muted-foreground"
                }
              >
                {detail}
              </p>
            </div>
          </li>
        ))}
      </ol>

      <Card>
        <CardContent className="flex flex-col gap-5 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-4">
            <span className="flex size-12 shrink-0 items-center justify-center rounded-full bg-warning/10 text-warning">
              <ClipboardListIcon aria-hidden />
            </span>
            <div>
              <p className="text-lg font-semibold">
                {unresolved.length || challenged.length} invoice lines need your
                decision
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                Review the challenged lines and approve the net challenge.
              </p>
            </div>
          </div>
          <Button size="lg" className="shrink-0" onClick={onReviewFindings}>
            Review {unresolved.length || challenged.length} challenged lines
            <ArrowRightIcon data-icon="inline-end" />
          </Button>
        </CardContent>
      </Card>

      {provisionalChallengeMappings.length ? (
        <Alert>
          <InfoIcon />
          <AlertTitle>Repair item approval required</AlertTitle>
          <AlertDescription>
            {provisionalChallengeMappings.length} challenged invoice line
            {provisionalChallengeMappings.length === 1 ? " has" : "s have"} a
            provisional repair item match. Approve the match before making the
            challenge decision.
          </AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardContent className="grid gap-0 p-0 sm:grid-cols-3">
          <div className="p-6">
            <p className="text-sm text-muted-foreground">
              Proposed payable net
            </p>
            <p className="mt-2 text-3xl font-semibold tracking-tight tabular-nums">
              {formatMoney(workspace.summary.challengePrice)}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Proposed payable net (incl. {formatMoney(workspace.invoice.mot)}{" "}
              non-VAT MOT)
            </p>
          </div>
          <div className="border-y p-6 sm:border-x sm:border-y-0">
            <p className="text-sm text-muted-foreground">Original net</p>
            <p className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">
              {formatMoney(workspace.invoice.netIncludingMot)}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Net invoice amount
            </p>
          </div>
          <div className="p-6">
            <p className="text-sm text-muted-foreground">Challenge amount</p>
            <p className="mt-2 text-2xl font-semibold tracking-tight text-destructive tabular-nums">
              {formatMoney(workspace.summary.challengeAmount)}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {workspace.summary.challengePercentage}% of net invoice
            </p>
          </div>
        </CardContent>
      </Card>

      <section>
        <h2 className="text-base font-semibold">Claim snapshot</h2>
        <div className="mt-4 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
          {[
            {
              label: "Incident date",
              value: workspace.claim.accidentDate,
              icon: CalendarDaysIcon,
            },
            {
              label: "Third-party vehicle",
              value: workspace.claim.thirdPartyVrm,
              icon: CarFrontIcon,
            },
            {
              label: "Repairer",
              value: workspace.invoice.garage,
              icon: Building2Icon,
            },
            {
              label: "Invoice",
              value: workspace.invoice.number,
              icon: FileTextIcon,
            },
          ].map((item) => {
            const Icon = item.icon
            return (
              <div key={item.label} className="flex items-center gap-3">
                <Icon className="text-muted-foreground" aria-hidden />
                <div>
                  <p className="text-xs text-muted-foreground">{item.label}</p>
                  <p className="mt-1 text-sm font-medium">{item.value}</p>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      <Alert className="py-5">
        <InfoIcon />
        <AlertTitle>Why this is challenged</AlertTitle>
        <AlertDescription className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <span>
            {challenged.length} invoice lines are priced above our approved and
            historical prices. We challenge only when the positive variance is
            at least £5 and 5%.
          </span>
          <Button
            variant="outline"
            className="shrink-0"
            onClick={onReviewFindings}
          >
            View calculation evidence
            <ArrowRightIcon data-icon="inline-end" />
          </Button>
        </AlertDescription>
      </Alert>

      <div className="flex items-center gap-2 border-t pt-5 text-xs text-muted-foreground">
        <LockKeyholeIcon aria-hidden />
        All figures are shown exclusive of VAT unless stated.
      </div>

      <Collapsible>
        <Card>
          <CardHeader className="py-4">
            <CollapsibleTrigger asChild>
              <Button
                variant="ghost"
                className="h-auto w-full justify-between p-0 text-left"
              >
                <span>
                  <span className="block font-semibold">
                    Claim and liability details
                  </span>
                  <span className="mt-1 block text-xs font-normal text-muted-foreground">
                    Review or update the handler decision and underlying claim
                    facts.
                  </span>
                </span>
                <ChevronDownIcon data-icon="inline-end" />
              </Button>
            </CollapsibleTrigger>
          </CardHeader>
          <CollapsibleContent>
            <CardContent className="grid gap-6 border-t pt-6 xl:grid-cols-2">
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
                      value={splitPercentage}
                      onChange={(event) =>
                        setSplitPercentage(event.target.value)
                      }
                    />
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
                  />
                  <FieldDescription>
                    Saved with the immutable audit record.
                  </FieldDescription>
                </Field>
                <Button
                  disabled={confirmed || confirming || !canConfirm}
                  onClick={() =>
                    onConfirm({
                      rationale: rationale.trim(),
                      splitLiabilityPercentage:
                        status === "SPLIT LIABILITY" ? splitValue : undefined,
                    })
                  }
                >
                  <CheckIcon data-icon="inline-start" />
                  {confirmed
                    ? "Liability confirmed"
                    : confirming
                      ? "Saving decision..."
                      : "Confirm liability"}
                </Button>
              </FieldGroup>
              <div className="flex flex-col gap-4 text-sm">
                {[
                  ["Policy number", workspace.claim.policyNumber],
                  ["Accident date", workspace.claim.accidentDate],
                  ["Location", workspace.claim.accidentLocation],
                  ["Paying insurer", workspace.claim.payingInsurer],
                  ["Claiming party", workspace.claim.claimingParty],
                  ["Accident", workspace.claim.accidentDescription],
                  ["Damage", workspace.claim.damageDescription],
                ].map(([label, value]) => (
                  <div key={label} className="grid grid-cols-[8rem_1fr] gap-4">
                    <span className="text-muted-foreground">{label}</span>
                    <span className="font-medium">{value}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>
    </>
  )
}
