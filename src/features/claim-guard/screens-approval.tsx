import {
  ArrowLeftIcon,
  ArrowRightIcon,
  CheckCircle2Icon,
  DownloadIcon,
  FileTextIcon,
  InfoIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { downloadBlob, type ClaimInvoiceSummary } from "@/lib/api"
import {
  acceptedChallengeRows,
  buildAcceptedChallengeCsv,
} from "./challenge-decision-export"
import { formatMoney } from "./format"
import type { ClaimWorkspace } from "./types"

export function ApprovalScreen({
  workspace,
  invoices,
  canIssue,
  comparisonReady,
  finalised,
  processing,
  enabled,
  caseUnresolvedChallenges,
  onFinalise,
  onDownload,
  onBackToFindings,
}: {
  workspace: ClaimWorkspace
  invoices: ClaimInvoiceSummary[]
  canIssue: boolean
  comparisonReady: boolean
  finalised: boolean
  processing: boolean
  enabled: boolean
  caseUnresolvedChallenges: number
  onFinalise: () => void
  onDownload: (format: "pdf") => void
  onBackToFindings: () => void
}) {
  const accepted = acceptedChallengeRows(invoices, workspace)
  const totalChallenge = accepted.reduce(
    (total, row) => total + row.challenge,
    0
  )
  const invoiceCount = new Set(accepted.map((row) => row.invoice)).size
  const canFinalise =
    enabled && canIssue && comparisonReady && caseUnresolvedChallenges === 0

  function downloadCsv() {
    downloadBlob(
      new Blob([`${buildAcceptedChallengeCsv(accepted)}\n`], {
        type: "text/csv;charset=utf-8",
      }),
      `claimguard-${workspace.claim.id}-accepted-challenges.csv`
    )
  }

  return (
    <>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Challenge decision
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Final summary of accepted invoice price challenges. Only accepted
            repair items are included here.
          </p>
        </div>
        <Badge
          variant={
            finalised
              ? "success"
              : caseUnresolvedChallenges
                ? "warning"
                : "outline"
          }
        >
          {finalised
            ? "Finalised"
            : caseUnresolvedChallenges
              ? "Review pending"
              : "Ready"}
        </Badge>
      </div>

      {caseUnresolvedChallenges ? (
        <Alert>
          <InfoIcon />
          <AlertTitle>Complete Review findings first</AlertTitle>
          <AlertDescription>
            {caseUnresolvedChallenges} challenged line
            {caseUnresolvedChallenges === 1 ? " still needs" : "s still need"} a
            reviewer decision. This summary includes accepted lines only.
          </AlertDescription>
        </Alert>
      ) : null}

      {!canIssue && !finalised ? (
        <Alert>
          <InfoIcon />
          <AlertTitle>Issuance is not ready</AlertTitle>
          <AlertDescription>
            The accepted summary is available, but liability must be confirmed
            under Advanced tools → Claim &amp; liability before the PDF can be
            issued.
          </AlertDescription>
        </Alert>
      ) : null}

      <section className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              Accepted lines
            </CardTitle>
          </CardHeader>
          <CardContent className="text-3xl font-semibold tabular-nums">
            {accepted.length}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              Invoices
            </CardTitle>
          </CardHeader>
          <CardContent className="text-3xl font-semibold tabular-nums">
            {invoiceCount}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              Total challenge
            </CardTitle>
          </CardHeader>
          <CardContent className="text-3xl font-semibold text-destructive tabular-nums">
            {formatMoney(totalChallenge)}
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Accepted challenged invoice items</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-right">Challenge amount</TableHead>
                  <TableHead>Invoice</TableHead>
                  <TableHead>Repairer</TableHead>
                  <TableHead>Repair item</TableHead>
                  <TableHead className="text-right">Billed price</TableHead>
                  <TableHead className="text-right">Supported price</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {accepted.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="text-right font-semibold text-destructive tabular-nums">
                      {formatMoney(row.challenge)}
                    </TableCell>
                    <TableCell className="font-medium">{row.invoice}</TableCell>
                    <TableCell>{row.repairer}</TableCell>
                    <TableCell>{row.repairItem}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMoney(row.billed)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMoney(row.supported)}
                    </TableCell>
                  </TableRow>
                ))}
                {!accepted.length ? (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className="py-10 text-center text-muted-foreground"
                    >
                      No accepted price challenges yet. Accept challenged items
                      in Review findings and they will appear here.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-col-reverse gap-3 border-t pt-5 sm:flex-row sm:items-center sm:justify-between">
        <Button type="button" variant="outline" onClick={onBackToFindings}>
          <ArrowLeftIcon data-icon="inline-start" />
          Back to challenged invoices
        </Button>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={!accepted.length}
            onClick={downloadCsv}
          >
            <DownloadIcon data-icon="inline-start" />
            Download CSV
          </Button>
          {finalised && accepted.length ? (
            <Button type="button" onClick={() => onDownload("pdf")}>
              <FileTextIcon data-icon="inline-start" />
              Download PDF
            </Button>
          ) : !finalised ? (
            <Button
              type="button"
              disabled={processing || !canFinalise}
              onClick={onFinalise}
            >
              <CheckCircle2Icon data-icon="inline-start" />
              {processing ? "Finalising…" : "Finalise accepted challenges"}
              <ArrowRightIcon data-icon="inline-end" />
            </Button>
          ) : null}
        </div>
      </div>
    </>
  )
}
