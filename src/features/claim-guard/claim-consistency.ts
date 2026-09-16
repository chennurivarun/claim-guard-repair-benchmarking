import type { ClaimWorkspace } from "./types"

export interface ConsistencyCheck {
  check: string
  finding: string
  status: "PASS" | "REVIEW"
}

function cleaned(value: string | null | undefined) {
  return (value ?? "").trim()
}

function registrationKey(value: string | null | undefined) {
  return cleaned(value).toLocaleUpperCase().replace(/[^A-Z0-9]/g, "")
}

function parsedDate(value: string | null | undefined) {
  const text = cleaned(value)
  if (!text) return null
  const parsed = new Date(text)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

/**
 * Compare the claim record against the invoice that is actually loaded.
 *
 * Only facts that are present on both sides are compared — a value missing
 * from either side is neither a match nor a conflict, so it produces no row at
 * all rather than an invented verdict. An empty result therefore means "there
 * was nothing to compare", which is what the screen says.
 */
export function claimInvoiceConsistencyChecks(
  workspace: ClaimWorkspace
): ConsistencyCheck[] {
  const checks: ConsistencyCheck[] = []

  const invoiceVrm = registrationKey(workspace.invoice.vrm)
  const claimVrms = [
    { label: "third-party vehicle", key: registrationKey(workspace.claim.thirdPartyVrm) },
    { label: "insured vehicle", key: registrationKey(workspace.claim.insuredVrm) },
  ].filter((entry) => entry.key)
  if (invoiceVrm && claimVrms.length) {
    const matched = claimVrms.find((entry) => entry.key === invoiceVrm)
    checks.push({
      check: "Invoice vehicle",
      finding: matched
        ? `${cleaned(workspace.invoice.vrm)} matches the ${matched.label} on the claim`
        : `${cleaned(workspace.invoice.vrm)} does not match any registration recorded on the claim`,
      status: matched ? "PASS" : "REVIEW",
    })
  }

  const accidentDate = parsedDate(workspace.claim.accidentDate)
  const invoiceDate = parsedDate(workspace.invoice.date)
  if (accidentDate && invoiceDate) {
    const afterAccident = invoiceDate.getTime() >= accidentDate.getTime()
    checks.push({
      check: "Invoice chronology",
      finding: afterAccident
        ? `${cleaned(workspace.invoice.date)} is on or after the ${cleaned(workspace.claim.accidentDate)} accident`
        : `${cleaned(workspace.invoice.date)} is before the ${cleaned(workspace.claim.accidentDate)} accident`,
      status: afterAccident ? "PASS" : "REVIEW",
    })
  }

  return checks
}
