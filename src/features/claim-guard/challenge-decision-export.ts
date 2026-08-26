import type { ClaimInvoiceSummary } from "@/lib/api"
import type { ClaimWorkspace } from "./types"

export interface AcceptedChallengeRow {
  id: string
  invoice: string
  repairer: string
  repairItem: string
  billed: number
  supported: number
  challenge: number
}

function normalisedStatus(value: string | null | undefined) {
  return (value ?? "").trim().toLocaleLowerCase().replaceAll("_", " ")
}

export function acceptedChallengeRows(
  invoices: ClaimInvoiceSummary[],
  workspace: ClaimWorkspace
): AcceptedChallengeRow[] {
  const rows = invoices.flatMap((invoice) =>
    (invoice.challenge_lines ?? [])
      .filter((line) => normalisedStatus(line.status) === "approved")
      .map((line) => ({
        id: `${invoice.id}:${line.line_id ?? line.id ?? line.description}`,
        invoice: invoice.invoice_number || invoice.document_filename,
        repairer: invoice.supplier_name || "Not recorded",
        repairItem: line.description || "Unlabelled repair item",
        billed: line.billed_net,
        supported: line.supported_net,
        challenge: line.challenge_net,
      }))
  )
  if (rows.length || invoices.length) return rows

  return workspace.lines
    .filter(
      (line) =>
        line.challenge > 0 &&
        normalisedStatus(line.challengeStatus) === "approved"
    )
    .map((line) => ({
      id: `${workspace.invoice.id}:${line.id}`,
      invoice: workspace.invoice.number || workspace.invoice.id,
      repairer: workspace.invoice.garage || "Not recorded",
      repairItem: line.description || "Unlabelled repair item",
      billed: line.currentTotal,
      supported: line.recommended ?? 0,
      challenge: line.challenge,
    }))
}

function csvCell(value: string | number) {
  const text = String(value)
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

export function buildAcceptedChallengeCsv(rows: AcceptedChallengeRow[]) {
  const header = [
    "challenge_amount",
    "invoice_number",
    "repairer",
    "repair_item",
    "billed_price",
    "supported_price",
  ]
  return [
    header.join(","),
    ...rows.map((row) =>
      [
        row.challenge.toFixed(2),
        row.invoice,
        row.repairer,
        row.repairItem,
        row.billed.toFixed(2),
        row.supported.toFixed(2),
      ]
        .map(csvCell)
        .join(",")
    ),
  ].join("\n")
}
