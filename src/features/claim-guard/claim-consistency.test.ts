import { describe, expect, it } from "vitest"

import { claimInvoiceConsistencyChecks } from "./claim-consistency"
import type { ClaimWorkspace } from "./types"

function workspace(
  claim: Partial<ClaimWorkspace["claim"]> = {},
  invoice: Partial<ClaimWorkspace["invoice"]> = {}
): ClaimWorkspace {
  return {
    liability: { status: "ADMITTED", humanConfirmed: true },
    claim: {
      id: "CG-CLIENT-001",
      status: "comparison_review",
      policyNumber: "",
      accidentDate: "",
      accidentLocation: "",
      accidentDescription: "",
      damageDescription: "",
      payingInsurer: "",
      claimingParty: "",
      insuredDriver: "",
      thirdPartyDriver: "",
      insuredVehicle: "",
      insuredVrm: "",
      thirdPartyVehicle: "",
      thirdPartyVrm: "",
      ...claim,
    },
    invoice: {
      id: "invoice-1",
      number: "",
      date: "",
      garage: "",
      address: "",
      vehicle: "",
      vrm: "",
      mileage: 0,
      partsNet: 0,
      labourNet: 0,
      taxableNet: 0,
      vat: 0,
      mot: 0,
      netIncludingMot: 0,
      gross: 0,
      ...invoice,
    },
    lines: [],
    summary: {
      challengePrice: 0,
      challengeAmount: 0,
      vatImpact: 0,
      grossEffect: 0,
      challengePercentage: 0,
      challengeStrength: 0,
    },
  }
}

describe("claim/invoice consistency checks", () => {
  it("produces no rows at all when nothing was read on both sides", () => {
    expect(claimInvoiceConsistencyChecks(workspace())).toEqual([])
  })

  it("does not compare a registration that only one side carries", () => {
    expect(
      claimInvoiceConsistencyChecks(workspace({}, { vrm: "AB12XYZ" }))
    ).toEqual([])
    expect(
      claimInvoiceConsistencyChecks(workspace({ insuredVrm: "AB12XYZ" }))
    ).toEqual([])
  })

  it("passes a registration that matches the claim, ignoring spacing and case", () => {
    const checks = claimInvoiceConsistencyChecks(
      workspace({ thirdPartyVrm: "ab12 xyz" }, { vrm: "AB12XYZ" })
    )

    expect(checks).toHaveLength(1)
    expect(checks[0]).toMatchObject({
      check: "Invoice vehicle",
      status: "PASS",
    })
    expect(checks[0].finding).toContain("third-party vehicle")
  })

  it("flags a registration that matches nothing on the claim", () => {
    const checks = claimInvoiceConsistencyChecks(
      workspace({ insuredVrm: "AB12XYZ" }, { vrm: "JK21MNO" })
    )

    expect(checks).toEqual([
      {
        check: "Invoice vehicle",
        finding:
          "JK21MNO does not match any registration recorded on the claim",
        status: "REVIEW",
      },
    ])
  })

  it("passes an invoice dated after the accident", () => {
    const checks = claimInvoiceConsistencyChecks(
      workspace({ accidentDate: "19 Nov 2025" }, { date: "26 Nov 2025" })
    )

    expect(checks).toEqual([
      {
        check: "Invoice chronology",
        finding: "26 Nov 2025 is on or after the 19 Nov 2025 accident",
        status: "PASS",
      },
    ])
  })

  it("flags an invoice dated before the accident", () => {
    const checks = claimInvoiceConsistencyChecks(
      workspace({ accidentDate: "19 Nov 2025" }, { date: "1 Nov 2025" })
    )

    expect(checks[0]).toMatchObject({
      check: "Invoice chronology",
      status: "REVIEW",
    })
  })

  it("skips the chronology check when either date was not printed at all", () => {
    expect(
      claimInvoiceConsistencyChecks(workspace({ accidentDate: "19 Nov 2025" }))
    ).toEqual([])
    expect(
      claimInvoiceConsistencyChecks(workspace({}, { date: "26 Nov 2025" }))
    ).toEqual([])
  })
})

// Registrations are compared after uppercasing. `toLocaleUpperCase` would map
// "i" to "İ" under a Turkish or Azeri host locale; the non-ASCII filter then
// strips it while a printed "I" survives, manufacturing a mismatch row for
// two registrations that are the same.
describe("registration comparison under a Turkish host locale", () => {
  it("matches a dotted-i registration regardless of the browser's locale", () => {
    const checks = claimInvoiceConsistencyChecks(
      workspace({ insuredVrm: "ai12 bcd" }, { vrm: "AI12BCD" })
    )

    expect(checks).toHaveLength(1)
    expect(checks[0]).toMatchObject({
      check: "Invoice vehicle",
      status: "PASS",
    })
  })

  it("does not depend on toLocaleUpperCase for the Turkish dotted capital", () => {
    // Proves the hazard is real: this is what the old implementation did.
    expect("ai12bcd".toLocaleUpperCase("tr")).not.toBe("AI12BCD")
    // …and that the check no longer follows it.
    expect(
      claimInvoiceConsistencyChecks(
        workspace({ insuredVrm: "ai12bcd" }, { vrm: "ai12bcd" })
      )[0]
    ).toMatchObject({ status: "PASS" })
  })
})

// The backend prints dates with Python's `%b`, which follows LC_TIME. Under a
// non-English locale it emits e.g. "16 sept. 2026". `new Date()` used to turn
// that into an Invalid Date, and the chronology row simply vanished — the
// screen then looked identical to one where the chronology had been checked
// and passed.
describe("a date the app cannot read", () => {
  it("reports that the chronology could not be checked instead of dropping it", () => {
    const checks = claimInvoiceConsistencyChecks(
      workspace({ accidentDate: "19 Nov 2025" }, { date: "16 sept. 2026" })
    )

    expect(checks).toHaveLength(1)
    expect(checks[0].check).toBe("Invoice chronology")
    expect(checks[0].status).toBe("REVIEW")
    expect(checks[0].finding).toContain("Could not be checked")
    expect(checks[0].finding).toContain("16 sept. 2026")
    expect(checks[0].finding).not.toContain("on or after")
  })

  it("names both dates when neither can be read", () => {
    const checks = claimInvoiceConsistencyChecks(
      workspace({ accidentDate: "not a date" }, { date: "also not a date" })
    )

    expect(checks[0].finding).toContain("also not a date")
    expect(checks[0].finding).toContain("not a date")
    expect(checks[0].status).toBe("REVIEW")
  })

  it("rejects a day that does not exist in that month", () => {
    const checks = claimInvoiceConsistencyChecks(
      workspace({ accidentDate: "19 Nov 2025" }, { date: "31 Feb 2026" })
    )

    expect(checks[0].finding).toContain("Could not be checked")
  })
})

describe("date parsing does not rely on the engine's Date parser", () => {
  it("orders D MMM YYYY dates correctly across a month and year boundary", () => {
    expect(
      claimInvoiceConsistencyChecks(
        workspace({ accidentDate: "31 Dec 2025" }, { date: "1 Jan 2026" })
      )[0]
    ).toMatchObject({ status: "PASS" })
    expect(
      claimInvoiceConsistencyChecks(
        workspace({ accidentDate: "1 Jan 2026" }, { date: "31 Dec 2025" })
      )[0]
    ).toMatchObject({ status: "REVIEW" })
  })

  it("treats the same day on both sides as on or after", () => {
    expect(
      claimInvoiceConsistencyChecks(
        workspace({ accidentDate: "9 Mar 2026" }, { date: "9 Mar 2026" })
      )[0]
    ).toMatchObject({ status: "PASS" })
  })

  it("accepts a lowercase month abbreviation but not a localised month name", () => {
    expect(
      claimInvoiceConsistencyChecks(
        workspace({ accidentDate: "1 jan 2026" }, { date: "2 jan 2026" })
      )[0]
    ).toMatchObject({ status: "PASS" })
    // Finnish "marras" is November; its first three letters are English March.
    // Guessing would silently shift the date by eight months, so it is
    // reported as unreadable instead.
    expect(
      claimInvoiceConsistencyChecks(
        workspace({ accidentDate: "1 Jan 2026" }, { date: "16 marras 2026" })
      )[0].finding
    ).toContain("Could not be checked")
  })
})
