import type {
  CaseLinkSweepResult,
  DocumentProcessingResult,
  IntakeGroup,
  UploadedDocument,
} from "./document-api"

/** One row of the hand-over, in the order it will be sent. */
export interface IntakeBatchEntry {
  file: File
  role: "invoice" | "estimate"
}

/** Everything `runIntakeBatch` reaches outside itself for. Injected rather
 * than imported so the ordering, the per-file isolation and the
 * exactly-once sweep can be asserted without a browser, a DOM or a network:
 * the review's point was that findings 2, 3 and 7 were all invisible to a
 * suite that only string-matched server-rendered markup. */
export interface IntakeBatchPorts {
  upload(
    file: File,
    caseReference: string,
    intakeGroup: IntakeGroup,
    pairedDocumentId?: string
  ): Promise<UploadedDocument>
  process(documentId: string): Promise<DocumentProcessingResult>
  sweep(caseReference: string): Promise<CaseLinkSweepResult>
  errorMessage(error: unknown): string
  /** Per-file progress, by position in `batch`. Keyed by position and never
   * by filename: two folders can hand over the same filename in one batch. */
  onStatus(index: number, status: string): void
  describeProcessed(document: UploadedDocument): string
}

export interface IntakeBatchOutcome {
  /** One "<filename>: <reason>" per file that did not make it in. */
  failures: string[]
  /** Non-null when the case-wide sweep itself failed. The files are stored
   * either way, so this is a notice with a retry, never a batch failure. */
  sweepError: string | null
  /** The document the reviewer is sent to: the first invoice of the batch.
   * With a folder, any other choice is alphabetical accident. */
  firstInvoiceDocumentId?: string
}

/** A whole hand-over at once: a folder of repair invoices and a folder of
 * engineer estimates. The sequencing matters and is deliberate.
 *
 * 1. Every invoice goes first, then every estimate -- an estimate can only
 *    be linked to an invoice the case already holds.
 * 2. Every file is uploaded under the same `intake_group`. The backend
 *    refuses to pair an estimate with an invoice from another group, so a
 *    mixed-group hand-over would silently never pair.
 * 3. A file that fails does not abort the batch. A folder of ten is not
 *    worth losing to one unreadable scan; the failure is reported on its own
 *    row and returned in `failures`.
 * 4. The case-wide link / gap-fill sweep runs exactly **once**, after the
 *    last file, and only if at least one file made it in.
 *
 * Why this loop and not `POST /claims/{ref}/documents/batch`, which enforces
 * 1, 2 and 4 server-side in a single round trip: the batch endpoint takes no
 * `paired_document_id`. That hint is what lets a one-invoice-plus-one-estimate
 * hand-over link two documents that share no comparable printed identity --
 * `_select_invoice` restricts its candidates to that one invoice and accepts
 * a zero-key match only there. Moving to the batch endpoint would drop it
 * silently for exactly the hand-over shape the setup screen was built for.
 * The loop also reports progress per file while the work happens, and has no
 * 50-file / 500 MB cap to split a folder around. */
export async function runIntakeBatch(
  batch: IntakeBatchEntry[],
  caseReference: string,
  group: IntakeGroup,
  ports: IntakeBatchPorts
): Promise<IntakeBatchOutcome> {
  const invoiceCount = batch.filter((row) => row.role === "invoice").length
  const estimateCount = batch.length - invoiceCount
  // The backend only accepts an explicit invoice link when the estimate
  // names a single-invoice document, so the hint is kept for the one
  // invoice + one estimate hand-over that used to be the only option. With a
  // folder of each, which estimate belongs to which invoice is the sweep's
  // job -- it sees the whole set, this loop does not.
  const explicitPairing = invoiceCount === 1 && estimateCount === 1
  let pairTarget: string | undefined
  let firstInvoiceDocumentId: string | undefined
  const failures: string[] = []

  for (const [index, { file, role }] of batch.entries()) {
    ports.onStatus(index, `Uploading (${index + 1} of ${batch.length})`)
    try {
      const document = await ports.upload(
        file,
        caseReference,
        group,
        role === "estimate" && explicitPairing ? pairTarget : undefined
      )
      ports.onStatus(index, "Extracting…")
      const result = await ports.process(document.id)
      if (result.document.kind === "repair_invoice") {
        pairTarget ??= document.id
        firstInvoiceDocumentId ??= document.id
      }
      ports.onStatus(index, ports.describeProcessed(result.document))
    } catch (error) {
      const message = ports.errorMessage(error)
      failures.push(`${file.name}: ${message}`)
      ports.onStatus(index, message)
    }
  }

  let sweepError: string | null = null
  if (failures.length < batch.length) {
    try {
      await ports.sweep(caseReference)
    } catch (error) {
      // The documents are stored either way; only the pairing pass is
      // missing, and it can be re-run from the screen without re-uploading.
      sweepError = ports.errorMessage(error)
    }
  }

  return { failures, sweepError, firstInvoiceDocumentId }
}
