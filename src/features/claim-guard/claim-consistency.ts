import type { ClaimWorkspace } from "./types"

export interface ConsistencyCheck {
  check: string
  finding: string
  status: "PASS" | "REVIEW"
}

function cleaned(value: string | null | undefined) {
  return (value ?? "").trim()
}

/**
 * Comparison form of a vehicle registration: uppercase, letters and digits.
 *
 * `toUpperCase`, not `toLocaleUpperCase`, on purpose. Under a Turkish or
 * Azeri host locale `"i"` uppercases to `"İ"`, which the `[^A-Z0-9]` filter
 * then strips while an already-uppercase `"I"` survives — so `ai12bcd` would
 * stop matching `AI12BCD` and the screen would print a mismatch that is not
 * one. Registration comparison must not depend on where the browser is.
 *
 * Deliberately narrower than the backend's `normalise_identifier`
 * (`backend/app/domain/normalisation.py`), which keeps `/` and is
 * Unicode-aware because the client's claim references print as
 * `base/incident`. This helper drops `/`, so it is for registrations only and
 * must not be reused for claim or policy numbers: it would collide
 * `123456/1` with the unrelated `1234561`, which is exactly the case the
 * backend docstring warns about. No UK registration prints a `/`, which is
 * why dropping it is safe here and nowhere else.
 */
function registrationKey(value: string | null | undefined) {
  return cleaned(value).toUpperCase().replace(/[^A-Z0-9]/g, "")
}

/** The month abbreviations Python's `%b` emits under an English `LC_TIME`. */
const MONTH_ABBREVIATIONS = [
  "jan",
  "feb",
  "mar",
  "apr",
  "may",
  "jun",
  "jul",
  "aug",
  "sep",
  "oct",
  "nov",
  "dec",
]

/**
 * Parse the one date shape the API emits: `D MMM YYYY`.
 *
 * `_date_label` (`backend/app/services/case_result.py`) formats dates as
 * `f"{value.day} {value:%b %Y}"`, e.g. `16 Sep 2026`.
 *
 * `new Date(text)` is not used: parsing anything other than ISO-8601 is
 * implementation-defined, so the same string can parse in one engine and not
 * another. Only the exact English abbreviation is accepted — a backend
 * running under a non-English `LC_TIME` emits something like `16 sept. 2026`,
 * and guessing at a foreign month name is worse than admitting the date could
 * not be read, because three-letter prefixes collide across locales (Finnish
 * `marras` is November, English `mar` is March).
 *
 * `null` means "this text is not a date this app can read" — which the caller
 * reports rather than hides.
 */
function parsedDate(value: string | null | undefined) {
  const match = /^(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})$/.exec(cleaned(value))
  if (!match) return null

  const day = Number(match[1])
  const month = MONTH_ABBREVIATIONS.indexOf(match[2].toLowerCase())
  const year = Number(match[3])
  if (month < 0) return null

  const parsed = new Date(Date.UTC(year, month, day))
  // Rejects impossible dates that would otherwise roll over (32 Jan, 31 Feb).
  if (parsed.getUTCMonth() !== month || parsed.getUTCDate() !== day) return null
  return parsed
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

  const accidentText = cleaned(workspace.claim.accidentDate)
  const invoiceText = cleaned(workspace.invoice.date)
  if (accidentText && invoiceText) {
    const accidentDate = parsedDate(accidentText)
    const invoiceDate = parsedDate(invoiceText)
    if (!accidentDate || !invoiceDate) {
      // Both dates were printed, so this check applies — it just could not be
      // run. Dropping the row would let an unreadable date read as a
      // chronology that was checked and passed.
      const unreadable = [
        invoiceDate ? null : `the invoice date "${invoiceText}"`,
        accidentDate ? null : `the accident date "${accidentText}"`,
      ]
        .filter(Boolean)
        .join(" and ")
      checks.push({
        check: "Invoice chronology",
        finding: `Could not be checked: ${unreadable} could not be read as a date`,
        status: "REVIEW",
      })
    } else {
      const afterAccident = invoiceDate.getTime() >= accidentDate.getTime()
      checks.push({
        check: "Invoice chronology",
        finding: afterAccident
          ? `${invoiceText} is on or after the ${accidentText} accident`
          : `${invoiceText} is before the ${accidentText} accident`,
        status: afterAccident ? "PASS" : "REVIEW",
      })
    }
  }

  return checks
}
