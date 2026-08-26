import { describe, expect, it } from "vitest"

import { buildManualReviewCsv } from "./manual-review-export"

describe("buildManualReviewCsv", () => {
  it("exports the review reason, AI briefing, pages, invoice and extracted lines", () => {
    const csv = buildManualReviewCsv(
      [
        {
          id: "doc-1",
          filename: "damaged,scan.pdf",
          status: "manual_review",
          page_count: 2,
          reprocess_required: false,
          manual_review: true,
          manual_review_reason: 'Parts table needs "human" confirmation',
          review_briefing: {
            document_summary: "A photographed repair invoice",
            content_found: ["bumper", "paint"],
            why_manual_review: "Low table confidence",
            recommended_action: "Check quantities",
            generated_at: "2026-08-26T10:00:00Z",
            model: "test-model",
            prompt_version: "v1",
            fallback: false,
          },
        },
      ],
      [
        {
          id: "page-2",
          document_id: "doc-1",
          document_filename: "damaged,scan.pdf",
          page_number: 2,
          width: null,
          height: null,
          page_type: "photo",
          classification_confidence: 0.8,
          classification_source: "pipeline",
          extraction_method: "ocr",
          rotation: 0,
          group_id: null,
          review_status: "manual_review",
          reprocess_required: false,
          correction: null,
          image_url: "/page-2",
        },
        {
          id: "page-1",
          document_id: "doc-1",
          document_filename: "damaged,scan.pdf",
          page_number: 1,
          width: null,
          height: null,
          page_type: "photo",
          classification_confidence: 0.8,
          classification_source: "pipeline",
          extraction_method: "ocr",
          rotation: 0,
          group_id: null,
          review_status: "manual_review",
          reprocess_required: false,
          correction: null,
          image_url: "/page-1",
        },
      ],
      [
        {
          id: "inv-1",
          document_id: "doc-1",
          invoice_number: "INV-1",
          invoice_date: "2026-08-26",
          document_filename: "damaged,scan.pdf",
          supplier_name: "Repairer Ltd",
          vehicle: {
            registration: "AB12 CDE",
            vin: null,
            make: "Audi",
            model: "A4",
            mileage: null,
          },
          totals: { gross: 100 },
          challenge_review: {
            positive: 0,
            approved: 0,
            rejected: 0,
            unresolved: 0,
          },
          lines: [{ description: "Rear bumper", line_total_net: 100 }],
        },
      ]
    )

    expect(csv).toContain('"damaged,scan.pdf"')
    expect(csv).toContain('"Parts table needs ""human"" confirmation"')
    expect(csv).toContain('"A photographed repair invoice"')
    expect(csv).toContain('"1 | 2"')
    expect(csv).toContain('"INV-1"')
    expect(csv).toContain('"Rear bumper"')
  })
})
