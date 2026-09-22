import { describe, expect, it } from "vitest"

import {
  runIntakeBatch,
  type IntakeBatchEntry,
  type IntakeBatchPorts,
} from "./intake-batch"
import type {
  CaseLinkSweepResult,
  DocumentProcessingResult,
  UploadedDocument,
} from "./document-api"

// The review's sharpest criticism was that `screens-client-intake.test.ts` is
// entirely SSR string-matching, so the batch loop, the invoice-before-estimate
// ordering, the per-file error isolation and the single-sweep guarantee had no
// coverage at all -- and a sweep pointed at the wrong endpoint, a sweep failure
// with no way back, and a per-file failure summary that could be silently
// overwritten all shipped. This file is that missing test: real orchestration,
// fake ports, no browser.

const CASE = "CG-2026-0048"

function file(name: string) {
  return new File([name], name, { type: "application/pdf" })
}

function uploaded(id: string, overrides: Partial<UploadedDocument> = {}) {
  return {
    id,
    filename: `${id}.pdf`,
    status: "ready",
    page_count: 1,
    reprocess_required: false,
    ...overrides,
  } as UploadedDocument
}

interface Recorder {
  uploads: Array<{
    name: string
    intakeGroup: string
    pairedDocumentId: string | undefined
  }>
  processed: string[]
  sweeps: string[]
  statuses: Array<{ index: number; status: string }>
}

function ports(
  recorder: Recorder,
  overrides: {
    failUpload?: (name: string) => boolean
    failSweep?: boolean
    kindOf?: (name: string) => UploadedDocument["kind"]
  } = {}
): IntakeBatchPorts {
  const kindOf =
    overrides.kindOf ??
    ((name: string) =>
      name.includes("estimate")
        ? ("engineer_assessment" as const)
        : ("repair_invoice" as const))
  return {
    async upload(source, caseReference, intakeGroup, pairedDocumentId) {
      recorder.uploads.push({
        name: source.name,
        intakeGroup,
        pairedDocumentId,
      })
      if (overrides.failUpload?.(source.name)) {
        throw new Error("The file is not a readable PDF.")
      }
      expect(caseReference).toBe(CASE)
      return uploaded(`doc-${source.name}`)
    },
    async process(documentId) {
      recorder.processed.push(documentId)
      const name = documentId.replace(/^doc-/, "")
      return {
        status: "processed",
        document: uploaded(documentId, { kind: kindOf(name), filename: name }),
      } as DocumentProcessingResult
    },
    async sweep(caseReference) {
      recorder.sweeps.push(caseReference)
      if (overrides.failSweep) throw new Error("The pairing sweep timed out.")
      return {
        case_reference: caseReference,
        assessments: 1,
        paired: 1,
        unpaired: 0,
        details: [],
      } satisfies CaseLinkSweepResult
    },
    errorMessage: (error) =>
      error instanceof Error ? error.message : "The request failed.",
    onStatus: (index, status) => recorder.statuses.push({ index, status }),
    describeProcessed: (document) =>
      document.kind === "engineer_assessment" ? "Estimate linked" : "Ingested",
  }
}

function recorder(): Recorder {
  return { uploads: [], processed: [], sweeps: [], statuses: [] }
}

function batchOf(invoices: string[], estimates: string[]): IntakeBatchEntry[] {
  return [
    ...invoices.map((name) => ({ file: file(name), role: "invoice" as const })),
    ...estimates.map((name) => ({
      file: file(name),
      role: "estimate" as const,
    })),
  ]
}

describe("a folder of invoices and a folder of estimates, handed over at once", () => {
  it("uploads every invoice before any estimate", async () => {
    const log = recorder()
    await runIntakeBatch(
      batchOf(["invoice-a.pdf", "invoice-b.pdf"], ["estimate-a.pdf"]),
      CASE,
      "live",
      ports(log)
    )

    // An estimate processed before any invoice exists can only report
    // "no invoice to pair with".
    expect(log.uploads.map((row) => row.name)).toEqual([
      "invoice-a.pdf",
      "invoice-b.pdf",
      "estimate-a.pdf",
    ])
  })

  it("uploads every file under the same intake group", async () => {
    const log = recorder()
    await runIntakeBatch(
      batchOf(["invoice-a.pdf"], ["estimate-a.pdf"]),
      CASE,
      "live",
      ports(log)
    )

    // `_select_invoice` refuses to pair across intake groups, so a mixed
    // hand-over would silently never pair.
    expect(new Set(log.uploads.map((row) => row.intakeGroup))).toEqual(
      new Set(["live"])
    )
  })

  it("runs the case-wide sweep exactly once, after the last file", async () => {
    const log = recorder()
    await runIntakeBatch(
      batchOf(
        ["invoice-a.pdf", "invoice-b.pdf", "invoice-c.pdf"],
        ["estimate-a.pdf", "estimate-b.pdf"]
      ),
      CASE,
      "live",
      ports(log)
    )

    expect(log.sweeps).toEqual([CASE])
    expect(log.processed).toHaveLength(5)
  })

  it("sends the explicit invoice hint only for a one-to-one hand-over", async () => {
    const one = recorder()
    await runIntakeBatch(
      batchOf(["invoice-a.pdf"], ["estimate-a.pdf"]),
      CASE,
      "live",
      ports(one)
    )
    expect(one.uploads.at(-1)?.pairedDocumentId).toBe("doc-invoice-a.pdf")

    const many = recorder()
    await runIntakeBatch(
      batchOf(["invoice-a.pdf", "invoice-b.pdf"], ["estimate-a.pdf"]),
      CASE,
      "live",
      ports(many)
    )
    // With a folder of each, which estimate belongs to which invoice is the
    // sweep's job: it sees the whole set, this loop does not.
    expect(many.uploads.at(-1)?.pairedDocumentId).toBeUndefined()
  })
})

describe("one bad file does not sink the hand-over", () => {
  it("keeps going, names the file that failed, and still sweeps", async () => {
    const log = recorder()
    const outcome = await runIntakeBatch(
      batchOf(["good-1.pdf", "broken.pdf", "good-2.pdf"], []),
      CASE,
      "live",
      ports(log, { failUpload: (name) => name === "broken.pdf" })
    )

    expect(outcome.failures).toEqual([
      "broken.pdf: The file is not a readable PDF.",
    ])
    expect(log.processed).toEqual(["doc-good-1.pdf", "doc-good-2.pdf"])
    expect(log.sweeps).toEqual([CASE])
    // The reviewer is sent to the first invoice that actually made it in.
    expect(outcome.firstInvoiceDocumentId).toBe("doc-good-1.pdf")
  })

  it("does not sweep when nothing made it in", async () => {
    const log = recorder()
    const outcome = await runIntakeBatch(
      batchOf(["broken-1.pdf", "broken-2.pdf"], []),
      CASE,
      "live",
      ports(log, { failUpload: () => true })
    )

    expect(outcome.failures).toHaveLength(2)
    expect(log.sweeps).toEqual([])
  })

  it("reports per-file progress by position, never by filename", async () => {
    // Two folders can hand over the same filename in one batch.
    const log = recorder()
    await runIntakeBatch(
      [
        { file: file("report.pdf"), role: "invoice" },
        { file: file("report.pdf"), role: "estimate" },
      ],
      CASE,
      "live",
      ports(log)
    )

    // Uploading, Extracting, then the outcome -- for each of the two rows.
    expect(log.statuses.filter((row) => row.index === 0)).toHaveLength(3)
    expect(log.statuses.filter((row) => row.index === 1)).toHaveLength(3)
    expect(log.statuses[0].status).toBe("Uploading (1 of 2)")
  })
})

describe("a failed sweep is a notice with a retry, not a failed hand-over", () => {
  it("keeps every file and reports the sweep failure on its own", async () => {
    const log = recorder()
    const outcome = await runIntakeBatch(
      batchOf(["invoice-a.pdf"], ["estimate-a.pdf"]),
      CASE,
      "live",
      ports(log, { failSweep: true })
    )

    // The files are stored and extracted either way -- only the pairing pass
    // is missing, and `rerunSweep` on the screen re-runs it with no upload.
    expect(outcome.failures).toEqual([])
    expect(outcome.sweepError).toBe("The pairing sweep timed out.")
    expect(log.processed).toEqual(["doc-invoice-a.pdf", "doc-estimate-a.pdf"])
  })

  it("does not throw out of the batch when the sweep throws", async () => {
    const log = recorder()
    await expect(
      runIntakeBatch(batchOf(["invoice-a.pdf"], []), CASE, "live", {
        ...ports(log, { failSweep: true }),
      })
    ).resolves.toMatchObject({ failures: [] })
  })
})

it("preserves the assessment picker intent without inventing a paired invoice", async () => {
  const log = recorder()
  const testPorts = ports(log)
  const hints: Array<string | undefined> = []
  const originalUpload = testPorts.upload
  testPorts.upload = async (file, ref, group, pair, kind) => {
    hints.push(kind)
    return originalUpload(file, ref, group, pair, kind)
  }
  const result = await runIntakeBatch(
    batchOf([], ["estimate-a.pdf", "estimate-b.pdf"]), CASE, "historical_claim", testPorts
  )
  expect(hints).toEqual(["engineer_assessment", "engineer_assessment"])
  expect(log.uploads.every((entry) => entry.pairedDocumentId === undefined)).toBe(true)
  expect(log.processed).toHaveLength(2)
  expect(log.sweeps).toEqual([CASE])
  expect(result.failures).toEqual([])
})
