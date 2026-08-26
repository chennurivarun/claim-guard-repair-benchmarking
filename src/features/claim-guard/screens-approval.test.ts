import { describe, expect, it } from "vitest"

import type { ClaimInvoiceSummary } from "@/lib/api"
import {
  acceptedChallengeRows,
  buildAcceptedChallengeCsv,
} from "./challenge-decision-export"
import { demoWorkspace } from "./demo-data"

function invoice(): ClaimInvoiceSummary {
  return {
    id: "invoice-1",
    invoice_number: "INV,001",
    invoice_date: "2026-08-26",
    document_filename: "invoice.pdf",
    supplier_name: "Example Repairs",
    totals: { gross: 500 },
    challenge_review: {
      positive: 2,
      approved: 1,
      rejected: 1,
      unresolved: 0,
    },
    challenge_lines: [
      {
        id: "challenge-1",
        line_id: "line-1",
        description: "Rear bumper",
        billed_net: 300,
        supported_net: 180,
        in_house_p90_net: 170,
        historical_claims_p90_net: 190,
        external_price_net: 180,
        challenge_net: 120,
        status: "approved",
        benchmark_source: "weighted",
      },
      {
        id: "challenge-2",
        line_id: "line-2",
        description: "Paint",
        billed_net: 100,
        supported_net: 80,
        in_house_p90_net: 80,
        historical_claims_p90_net: null,
        external_price_net: null,
        challenge_net: 20,
        status: "rejected",
        benchmark_source: "in_house",
      },
    ],
    lines: [],
  }
}

describe("accepted challenge summary", () => {
  it("includes approved challenge lines only", () => {
    const rows = acceptedChallengeRows([invoice()], demoWorkspace)

    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      invoice: "INV,001",
      repairItem: "Rear bumper",
      challenge: 120,
    })
  })

  it("exports challenge amount as the first CSV column", () => {
    const csv = buildAcceptedChallengeCsv(
      acceptedChallengeRows([invoice()], demoWorkspace)
    )

    expect(csv.split("\n")[0]).toBe(
      "challenge_amount,invoice_number,repairer,repair_item,billed_price,supported_price"
    )
    expect(csv.split("\n")[1]).toBe(
      '120.00,"INV,001",Example Repairs,Rear bumper,300.00,180.00'
    )
  })
})
