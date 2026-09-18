import { describe, expect, it } from "vitest"

import {
  INTAKE_GROUP_LABELS,
  intakeGroupsFor,
  screenScope,
  sourceScreen,
} from "./source-scope"

describe("each sub-screen knows which source it serves", () => {
  it("scopes the third-party screens to historical_claim", () => {
    expect(screenScope("tp-upload")).toEqual({
      step: "upload",
      intakeGroup: "historical_claim",
    })
    expect(screenScope("tp-intelligence")).toEqual({
      step: "intelligence",
      intakeGroup: "historical_claim",
    })
    expect(screenScope("tp-benchmarks")).toEqual({
      step: "benchmarks",
      intakeGroup: "historical_claim",
    })
  })

  it("scopes the Aviva DLG screens to in_house", () => {
    expect(screenScope("dlg-upload")?.intakeGroup).toBe("in_house")
    expect(screenScope("dlg-intelligence")?.intakeGroup).toBe("in_house")
    expect(screenScope("dlg-benchmarks")?.intakeGroup).toBe("in_house")
  })

  it("scopes the new invoice screens to live", () => {
    expect(screenScope("new-invoice-upload")).toEqual({
      step: "upload",
      intakeGroup: "live",
    })
    expect(screenScope("new-invoice-intelligence")).toEqual({
      step: "intelligence",
      intakeGroup: "live",
    })
    expect(screenScope("benchmark-analysis")).toEqual({
      step: "analysis",
      intakeGroup: "live",
    })
  })

  it("leaves the Advanced tools screens unscoped", () => {
    expect(screenScope("upload-processing")).toBeNull()
    expect(screenScope("benchmark-dashboard")).toBeNull()
  })
})

describe("after a batch lands, the upload goes to that source's Document intelligence", () => {
  it("routes each source to its own next step", () => {
    expect(sourceScreen("historical_claim", "intelligence")).toBe(
      "tp-intelligence"
    )
    expect(sourceScreen("in_house", "intelligence")).toBe("dlg-intelligence")
    expect(sourceScreen("live", "intelligence")).toBe(
      "new-invoice-intelligence"
    )
    expect(sourceScreen("live", "analysis")).toBe("benchmark-analysis")
    expect(sourceScreen("in_house", "upload")).toBe("dlg-upload")
  })
})

describe("the upload screen offers exactly one bucket when scoped", () => {
  it("offers only the scoped group", () => {
    expect(intakeGroupsFor({ setup: false, scope: "historical_claim" })).toEqual([
      "historical_claim",
    ])
    expect(intakeGroupsFor({ setup: true, scope: "in_house" })).toEqual([
      "in_house",
    ])
  })

  it("keeps the unscoped behaviour for the Advanced tools screens", () => {
    expect(intakeGroupsFor({ setup: true })).toEqual([
      "historical_claim",
      "in_house",
    ])
    expect(intakeGroupsFor({ setup: false })).toEqual(["live"])
  })

  it("names the buckets the way she does", () => {
    expect(INTAKE_GROUP_LABELS.historical_claim).toBe(
      "Third party insured invoices"
    )
    expect(INTAKE_GROUP_LABELS.in_house).toBe("Aviva DLG invoices")
  })
})
