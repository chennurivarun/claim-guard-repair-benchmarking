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

  it("skips the chronology check when either date is missing or unparseable", () => {
    expect(
      claimInvoiceConsistencyChecks(workspace({ accidentDate: "19 Nov 2025" }))
    ).toEqual([])
    expect(
      claimInvoiceConsistencyChecks(
        workspace({ accidentDate: "not a date" }, { date: "26 Nov 2025" })
      )
    ).toEqual([])
  })
})
