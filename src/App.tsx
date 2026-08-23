import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { Toaster } from "@/components/ui/sonner"
import { AppShell } from "@/features/claim-guard/app-shell"
import { demoWorkspace } from "@/features/claim-guard/demo-data"
import {
  LineCorrectionSheet,
  SettlementDialog,
  type LineCorrectionValues,
  type SettlementValues,
} from "@/features/claim-guard/review-overlays"
import {
  AuditReportsScreen,
  MissingItemsScreen,
  OntologyBankScreen,
} from "@/features/claim-guard/screens-challenge-admin"
import { ApprovalScreen } from "@/features/claim-guard/screens-approval"
import {
  DocumentPagesScreen,
  ExtractedInvoiceScreen,
  UploadProcessingScreen,
} from "@/features/claim-guard/screens-liability-documents"
import { ReviewFindingsScreen } from "@/features/claim-guard/screens-review-findings"
import { BenchmarkDashboardScreen } from "@/features/claim-guard/screens-benchmark-dashboard"
import { KnowledgeGraphScreen } from "@/features/claim-guard/screens-knowledge-graph"
import {
  CalculationChecksScreen,
  OntologyMappingScreen,
} from "@/features/claim-guard/screens-validation"
import type {
  ClaimWorkspace,
  InvoiceLine,
  LiabilityStatus,
  ScreenId,
} from "@/features/claim-guard/types"
import {
  confirmLiability,
  correctInvoiceLine,
  decideExtractionLine,
  decideChallenge,
  decideLineMapping,
  downloadBlob,
  downloadDemoJson,
  fetchClaimInvoices,
  fetchClaimWorkspace,
  finaliseClaim,
  getApiErrorMessage,
  loadClaimWorkspace,
  approveResearchItem,
  recordSettlement,
  requestReport,
  runClaimComparison,
  startLineResearch,
  type ManualResearchInput,
  type MappingDecisionInput,
  type ReportFormat,
  type ExtractionDecision,
  type ClaimInvoiceSummary,
} from "@/lib/api"

const HANDLER_ID = "pilot.handler"

const GENERIC_INVOICE_VALUES = new Set([
  "",
  "-",
  "invoice",
  "invoice no",
  "invoice number",
  "inv",
  "inv no",
  "inv number",
  "n/a",
  "na",
  "none",
  "repair invoice",
  "tax invoice",
  "unknown",
])

const GENERIC_SUPPLIER_VALUES = new Set([
  "",
  "-",
  "garage",
  "invoice",
  "n/a",
  "na",
  "none",
  "repair invoice",
  "repairer",
  "supplier",
  "unknown",
  "unknown repairer",
])

function usableDisplayValue(
  value: string | null,
  genericValues: Set<string>
): string | null {
  const cleaned = value?.trim() ?? ""
  const token = cleaned
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
  return genericValues.has(token) ? null : cleaned
}

function invoiceDisplayLabel(
  invoice: ClaimInvoiceSummary,
  index: number
): string {
  const invoiceNumber = usableDisplayValue(
    invoice.invoice_number,
    GENERIC_INVOICE_VALUES
  )
  const supplierName = usableDisplayValue(
    invoice.supplier_name,
    GENERIC_SUPPLIER_VALUES
  )
  const primary = invoiceNumber
    ? `Invoice ${invoiceNumber}`
    : invoice.document_filename
      ? `${invoice.document_filename} · Invoice ${index + 1}`
      : `Invoice ${index + 1}`
  return supplierName ? `${primary} · ${supplierName}` : primary
}

export function App() {
  const [workspace, setWorkspace] = useState<ClaimWorkspace>(demoWorkspace)
  const [apiMode, setApiMode] = useState<"api" | "demo">("demo")
  const [activeScreen, setActiveScreen] =
    useState<ScreenId>("upload-processing")
  const [liabilityStatus, setLiabilityStatus] = useState<LiabilityStatus>(
    demoWorkspace.liability.status
  )
  const [liabilityConfirmed, setLiabilityConfirmed] = useState(
    demoWorkspace.liability.humanConfirmed
  )
  const [selectedLine, setSelectedLine] = useState<InvoiceLine | null>(null)
  const [correctionOpen, setCorrectionOpen] = useState(false)
  const [settlementOpen, setSettlementOpen] = useState(false)
  const [liabilitySaving, setLiabilitySaving] = useState(false)
  const [correctionSaving, setCorrectionSaving] = useState(false)
  const [extractionSavingLineId, setExtractionSavingLineId] = useState<
    string | null
  >(null)
  const [settlementSaving, setSettlementSaving] = useState(false)
  const [challengeSaving, setChallengeSaving] = useState(false)
  const [researchSaving, setResearchSaving] = useState(false)
  const [mappingSavingLineId, setMappingSavingLineId] = useState<string | null>(
    null
  )
  const [comparisonSaving, setComparisonSaving] = useState(false)
  const [invoices, setInvoices] = useState<ClaimInvoiceSummary[]>([])
  const [focusDocumentId, setFocusDocumentId] = useState<string | null>(null)
  const [p90ThresholdPct, setP90ThresholdPct] = useState(10)
  const [thresholdApplying, setThresholdApplying] = useState(false)

  useEffect(() => {
    void loadClaimWorkspace(p90ThresholdPct).then((result) => {
      setWorkspace(result.workspace)
      setApiMode(result.mode)
      setLiabilityStatus(result.workspace.liability.status)
      setLiabilityConfirmed(result.workspace.liability.humanConfirmed)
      if (result.errorMessage) {
        toast.error("ClaimGuard API is not ready", {
          description: `${result.errorMessage} Demo data is shown read-only.`,
        })
      } else {
        void fetchClaimInvoices(result.workspace.claim.id).then(setInvoices)
      }
    })
    // Only the initial p90ThresholdPct matters here; later changes are
    // handled by the dedicated threshold-refetch effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The server now computes the operational price decision (P90 policy) for
  // every line — the client no longer overlays it. Toggling the threshold
  // just refetches the workspace with the new p90_threshold_pct. Demo mode
  // has no backend to refetch from, so the toggle is a silent no-op there,
  // matching how the benchmark dashboard already treats demo mode.
  const isFirstThresholdRender = useRef(true)
  useEffect(() => {
    if (isFirstThresholdRender.current) {
      isFirstThresholdRender.current = false
      return
    }
    if (apiMode !== "api") return
    // Synchronous setState here is intentional: it flips on the Benchmarks
    // screen's "Applying threshold…" indicator for the refetch this effect
    // triggers, mirroring the saving-flag pattern used by the handlers above.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setThresholdApplying(true)
    fetchClaimWorkspace(
      workspace.claim.id,
      workspace.invoice.id,
      p90ThresholdPct
    )
      .then((next) => applyWorkspace(next))
      .catch((error) => {
        toast.error("Could not apply the new threshold", {
          description: getApiErrorMessage(error),
        })
      })
      .finally(() => setThresholdApplying(false))
    // Re-running this on workspace.claim.id/invoice.id would refetch on
    // every unrelated workspace update; it only needs to react to the
    // threshold itself, using whatever claim/invoice is current at the time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p90ThresholdPct])

  const issuanceAllowed =
    liabilityConfirmed &&
    (liabilityStatus === "ADMITTED" || liabilityStatus === "SPLIT LIABILITY")
  const caseStatus = workspace.claim.status.toLowerCase()
  const caseFinalised = caseStatus === "finalised"
  const comparisonReady = caseStatus === "comparison_review"
  const pendingReviewInvoice = invoices.find(
    (invoice) =>
      invoice.id !== workspace.invoice.id &&
      (invoice.challenge_review?.unresolved ?? 0) > 0
  )
  const caseUnresolvedChallenges = invoices.reduce(
    (total, invoice) => total + (invoice.challenge_review?.unresolved ?? 0),
    0
  )
  const challengedInvoices = invoices.filter(
    (invoice) => (invoice.challenge_review?.positive ?? 0) > 0
  )
  // The Review findings screen only makes sense for invoices with a positive
  // price challenge; every other screen keeps the full uploaded-invoice list.
  const invoiceSelectorOptions =
    activeScreen === "price-comparison" ? challengedInvoices : invoices

  useEffect(() => {
    if (activeScreen !== "price-comparison") return
    const qualifying = invoices.filter(
      (invoice) => (invoice.challenge_review?.positive ?? 0) > 0
    )
    if (!qualifying.length) return
    if (qualifying.some((invoice) => invoice.id === workspace.invoice.id)) {
      return
    }
    void handleInvoiceSelection(qualifying[0].id)
    // handleInvoiceSelection is a stable function declaration recreated each
    // render; the guards above already prevent redundant or looping calls.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeScreen, invoices, workspace.invoice.id])

  function applyWorkspace(nextWorkspace: ClaimWorkspace) {
    setWorkspace(nextWorkspace)
    setLiabilityStatus(nextWorkspace.liability.status)
    setLiabilityConfirmed(nextWorkspace.liability.humanConfirmed)
  }

  async function refreshWorkspace(invoiceId?: string) {
    const next = await fetchClaimWorkspace(
      workspace.claim.id,
      invoiceId,
      p90ThresholdPct
    )
    applyWorkspace(next)
    setInvoices(await fetchClaimInvoices(next.claim.id))
    return next
  }

  function navigate(screen: ScreenId) {
    setActiveScreen(screen)
  }

  function openManualReview(documentId: string) {
    setFocusDocumentId(documentId)
    navigate("missing-items")
  }

  function changeLiabilityStatus(status: LiabilityStatus) {
    setLiabilityStatus(status)
    setLiabilityConfirmed(false)
  }

  function inspectLine(line: InvoiceLine) {
    setSelectedLine(line)
    setCorrectionOpen(true)
  }

  async function handleInvoiceSelection(invoiceId: string) {
    try {
      await refreshWorkspace(invoiceId)
      toast.success("Invoice view changed")
    } catch (error) {
      toast.error("Invoice could not be opened", {
        description: getApiErrorMessage(error),
      })
    }
  }

  async function refreshComparison(invoiceId?: string) {
    await runClaimComparison(workspace.claim.id)
    return refreshWorkspace(invoiceId)
  }

  async function handleRunComparison(
    destination: ScreenId = "ontology-mapping"
  ) {
    if (apiMode !== "api") {
      toast.error("Comparison requires the FastAPI service")
      return
    }
    setComparisonSaving(true)
    try {
      await refreshComparison(workspace.invoice.id)
      navigate(destination)
      toast.success("Ontology mapping and price comparison completed")
    } catch (error) {
      toast.error("Comparison could not run", {
        description: getApiErrorMessage(error),
      })
    } finally {
      setComparisonSaving(false)
    }
  }

  async function handleLiabilityConfirmation(decision: {
    rationale: string
    splitLiabilityPercentage?: number
  }) {
    if (apiMode === "demo") {
      setLiabilityConfirmed(true)
      setWorkspace((current) => ({
        ...current,
        liability: {
          ...current.liability,
          status: liabilityStatus,
          humanConfirmed: true,
          confirmedBy: HANDLER_ID,
          rationale: decision.rationale,
          splitLiabilityPercentage: decision.splitLiabilityPercentage ?? null,
        },
      }))
      toast.success("Demo liability decision saved locally", {
        description: liabilityStatus,
      })
      return
    }

    setLiabilitySaving(true)
    try {
      await confirmLiability(workspace.claim.id, {
        status: liabilityStatus,
        confirmedBy: HANDLER_ID,
        rationale: decision.rationale,
        splitLiabilityPercentage: decision.splitLiabilityPercentage,
      })
    } catch (error) {
      toast.error("Liability decision was not saved", {
        description: getApiErrorMessage(error),
      })
      setLiabilitySaving(false)
      return
    }

    try {
      applyWorkspace(
        await fetchClaimWorkspace(
          workspace.claim.id,
          workspace.invoice.id,
          p90ThresholdPct
        )
      )
      toast.success("Liability decision confirmed", {
        description: liabilityStatus,
      })
    } catch (error) {
      setLiabilityConfirmed(true)
      setWorkspace((current) => ({
        ...current,
        liability: {
          ...current.liability,
          status: liabilityStatus,
          humanConfirmed: true,
          confirmedBy: HANDLER_ID,
          rationale: decision.rationale,
          splitLiabilityPercentage: decision.splitLiabilityPercentage ?? null,
        },
      }))
      toast.warning("Liability saved, but the workspace could not refresh", {
        description: getApiErrorMessage(error),
      })
    } finally {
      setLiabilitySaving(false)
    }
  }

  async function handleLineCorrection(values: LineCorrectionValues) {
    if (!selectedLine) return
    const lineTotalNet =
      Math.round(values.quantity * values.unitPrice * 100) / 100

    if (apiMode === "demo") {
      setWorkspace((current) => ({
        ...current,
        lines: current.lines.map((line) =>
          line.id === selectedLine.id
            ? {
                ...line,
                description: values.description,
                quantity: values.quantity,
                unitPrice: values.unitPrice,
                currentTotal: lineTotalNet,
                extractionReviewStatus: "corrected",
                requiresExtractionReview: false,
              }
            : line
        ),
      }))
      setCorrectionOpen(false)
      toast.success("Demo correction saved locally", {
        description: "Original fixture values remain available after reload.",
      })
      return
    }

    setCorrectionSaving(true)
    try {
      await correctInvoiceLine(selectedLine.id, {
        actor: HANDLER_ID,
        reason: values.reason,
        description: values.description,
        quantity: values.quantity,
        unitPriceNet: values.unitPrice,
        lineTotalNet,
      })
    } catch (error) {
      toast.error("Correction was not saved", {
        description: getApiErrorMessage(error),
      })
      setCorrectionSaving(false)
      return
    }

    try {
      applyWorkspace(
        await fetchClaimWorkspace(
          workspace.claim.id,
          undefined,
          p90ThresholdPct
        )
      )
      toast.success("Correction saved", {
        description:
          "Reprocess the invoice and rerun comparison before challenge finalisation.",
      })
    } catch (error) {
      setWorkspace((current) => ({
        ...current,
        claim: { ...current.claim, status: "extraction_review" },
        lines: current.lines.map((line) =>
          line.id === selectedLine.id
            ? {
                ...line,
                description: values.description,
                quantity: values.quantity,
                unitPrice: values.unitPrice,
                currentTotal: lineTotalNet,
              }
            : line
        ),
      }))
      toast.warning("Correction saved, but the workspace could not refresh", {
        description: `${getApiErrorMessage(error)} Reprocessing and recomparison are still required.`,
      })
    } finally {
      setCorrectionOpen(false)
      setCorrectionSaving(false)
    }
  }

  async function handleExtractionDecision(
    line: InvoiceLine,
    decision: ExtractionDecision,
    reason?: string
  ) {
    const nextStatus = decision === "undo" ? "needs_review" : decision
    if (apiMode === "demo") {
      setWorkspace((current) => ({
        ...current,
        lines: current.lines.map((item) =>
          item.id === line.id
            ? {
                ...item,
                extractionReviewStatus: nextStatus,
                requiresExtractionReview: decision === "undo",
              }
            : item
        ),
      }))
      toast.success(`Demo extraction ${decision} saved locally`)
      return
    }

    setExtractionSavingLineId(line.id)
    try {
      await decideExtractionLine(line.id, {
        decision,
        actor: HANDLER_ID,
        reason,
      })
      applyWorkspace(
        await fetchClaimWorkspace(
          workspace.claim.id,
          undefined,
          p90ThresholdPct
        )
      )
      toast.success(
        decision === "undo"
          ? "Extraction decision undone"
          : `Extraction ${decision}`
      )
    } catch (error) {
      toast.error("Extraction decision was not saved", {
        description: getApiErrorMessage(error),
      })
    } finally {
      setExtractionSavingLineId(null)
    }
  }

  async function handleSettlement(values: SettlementValues) {
    if (apiMode === "demo") {
      setSettlementOpen(false)
      toast.success("Demo settlement captured locally", {
        description: `Invoice-level net settlement £${values.agreedAmountNet.toFixed(2)}`,
      })
      return
    }

    setSettlementSaving(true)
    try {
      await recordSettlement(workspace.invoice.id, {
        agreedAmountNet: values.agreedAmountNet,
        agreedAt: new Date().toISOString(),
        recordedBy: HANDLER_ID,
        note: "Invoice-level settlement recorded in ClaimGuard.",
        lines: values.lines,
      })
      setSettlementOpen(false)
      toast.success("Settlement captured", {
        description: `Invoice-level net settlement £${values.agreedAmountNet.toFixed(2)}`,
      })
    } catch (error) {
      toast.error("Settlement was not saved", {
        description: getApiErrorMessage(error),
      })
    } finally {
      setSettlementSaving(false)
    }
  }

  async function handleMappingDecision(
    line: InvoiceLine,
    input: Omit<MappingDecisionInput, "actor">
  ) {
    if (apiMode === "demo") {
      throw new Error(
        "Mapping decisions require the FastAPI service; demo mode never records a fake approval."
      )
    }

    setMappingSavingLineId(line.id)
    let decisionSaved = false
    try {
      await decideLineMapping(workspace.claim.id, line.id, {
        ...input,
        actor: HANDLER_ID,
      })
      decisionSaved = true
      await refreshWorkspace(workspace.invoice.id)
      toast.success("Mapping decision saved", {
        description: `${line.description} · ${input.decision.toUpperCase()}`,
      })
    } catch (error) {
      toast.error(
        decisionSaved
          ? "Mapping saved, but the workspace could not refresh"
          : "Mapping decision was not saved",
        { description: getApiErrorMessage(error) }
      )
      throw error
    } finally {
      setMappingSavingLineId(null)
    }
  }

  async function handleChallengeDecision(
    line: InvoiceLine,
    decision: {
      approved: boolean
      rationale: string
      challengePriceNet?: number
    }
  ) {
    if (apiMode === "demo") {
      const error = new Error(
        "Challenge decisions require the FastAPI service; demo mode never records a fake decision."
      )
      toast.error("Challenge decision was not saved", {
        description: error.message,
      })
      throw error
    }
    if (!line.challengeResultId) {
      throw new Error(`Challenge result is missing for ${line.description}.`)
    }
    setChallengeSaving(true)
    try {
      await decideChallenge(line.challengeResultId, {
        actor: HANDLER_ID,
        ...decision,
      })
      await refreshWorkspace(workspace.invoice.id)
      toast.success(
        decision.approved
          ? decision.challengePriceNet === undefined
            ? "Line challenge accepted"
            : "Edited supported net price accepted"
          : "Line challenge rejected",
        { description: line.description }
      )
    } catch (error) {
      toast.error("Challenge decision was not saved", {
        description: getApiErrorMessage(error),
      })
      throw error
    } finally {
      setChallengeSaving(false)
    }
  }

  async function handleChallengeFinalise() {
    if (!issuanceAllowed || !comparisonReady) {
      toast.error("Challenge issuance is gated", {
        description: !issuanceAllowed
          ? "Confirm ADMITTED or SPLIT LIABILITY before finalising."
          : "Reprocess the corrected invoice and rerun comparison before finalising.",
      })
      return
    }

    if (apiMode === "demo") {
      toast.error("Finalisation requires the FastAPI service", {
        description: "Demo mode never records a fake challenge approval.",
      })
      return
    }

    setChallengeSaving(true)
    try {
      await finaliseClaim(workspace.claim.id, HANDLER_ID)
    } catch (error) {
      try {
        applyWorkspace(
          await fetchClaimWorkspace(
            workspace.claim.id,
            undefined,
            p90ThresholdPct
          )
        )
      } catch {
        // Keep the current view when the follow-up refresh also fails.
      }
      toast.error("Challenge could not be finalised", {
        description: getApiErrorMessage(error),
      })
      setChallengeSaving(false)
      return
    }

    try {
      applyWorkspace(
        await fetchClaimWorkspace(
          workspace.claim.id,
          undefined,
          p90ThresholdPct
        )
      )
      toast.success("Challenge approved and case finalised", {
        description: "DOCX and PDF negotiation outputs are now available.",
      })
    } catch (error) {
      setWorkspace((current) => ({
        ...current,
        claim: { ...current.claim, status: "finalised" },
        lines: current.lines.map((line) =>
          line.challenge > 0
            ? { ...line, challengeApproved: true, challengeStatus: "approved" }
            : line
        ),
      }))
      toast.warning("Case finalised, but the workspace could not refresh", {
        description: getApiErrorMessage(error),
      })
    } finally {
      setChallengeSaving(false)
    }
  }

  async function handleResearch(
    line: InvoiceLine,
    values: import("@/features/claim-guard/screens-challenge-admin").ResearchFormValues
  ) {
    if (apiMode === "demo") {
      const error = new Error(
        "Research requires the FastAPI service; demo mode never creates provisional evidence."
      )
      toast.error("Research evidence was not saved", {
        description: error.message,
      })
      throw error
    }
    const input: ManualResearchInput = {
      requestedBy: HANDLER_ID,
      queryText: `Research invoice line: ${line.description}`,
      sourceAllowListVersion: values.sourceAllowListVersion,
      suggestion: {
        canonicalName: values.canonicalName,
        itemType: values.itemType,
        category: values.category,
        unit: values.unit,
        priceNet: values.priceNet,
        dateChecked: values.dateChecked,
        rationale: values.rationale,
        partNumber: line.partNumber,
        confidence: values.confidence,
      },
      evidence: {
        sourceUri: values.sourceUri,
        title: values.evidenceTitle,
        priceNet: values.priceNet,
        unit: values.unit,
        partNumber: line.partNumber,
        minimalExcerpt: values.rationale,
      },
    }
    setResearchSaving(true)
    try {
      await startLineResearch(workspace.claim.id, line.id, input)
      applyWorkspace(
        await fetchClaimWorkspace(
          workspace.claim.id,
          undefined,
          p90ThresholdPct
        )
      )
      toast.success("Provisional research evidence saved", {
        description:
          "A handler approval is still required before it enters the bank.",
      })
    } catch (error) {
      toast.error("Research evidence was not saved", {
        description: getApiErrorMessage(error),
      })
      throw error
    } finally {
      setResearchSaving(false)
    }
  }

  async function handleResearchApproval(
    item: NonNullable<ClaimWorkspace["researchItems"]>[number]
  ) {
    if (apiMode === "demo" || !item.researchItemId) {
      const error = new Error(
        "A persisted research item is required for approval."
      )
      toast.error("Ontology item was not approved", {
        description: error.message,
      })
      throw error
    }
    setResearchSaving(true)
    try {
      await approveResearchItem(item.researchItemId, {
        approvedBy: HANDLER_ID,
        reviewerNote:
          "Handler approved the researched ontology item for the pilot.",
      })
      applyWorkspace(
        await fetchClaimWorkspace(
          workspace.claim.id,
          undefined,
          p90ThresholdPct
        )
      )
      toast.success("Ontology item approved", {
        description:
          "The bank version and claim comparison were refreshed immutably.",
      })
    } catch (error) {
      toast.error("Ontology item was not approved", {
        description: getApiErrorMessage(error),
      })
      throw error
    } finally {
      setResearchSaving(false)
    }
  }

  function handleReport(format: ReportFormat) {
    if (apiMode === "demo") {
      if (format === "json") {
        downloadDemoJson()
        toast.success("Demo JSON downloaded")
      } else {
        toast.info(
          `${format.toUpperCase()} export is ready when the FastAPI service is connected`,
          {
            description:
              "The JSON evidence pack remains available in demo mode.",
          }
        )
      }
      return
    }

    void requestReport(format, workspace.claim.id)
      .then((blob) => {
        downloadBlob(
          blob,
          `claimguard-${workspace.claim.id}.${format === "sqlite" ? "db" : format}`
        )
        toast.success(`${format.toUpperCase()} report downloaded`)
      })
      .catch((error) =>
        toast.error("The report service could not complete this export", {
          description: getApiErrorMessage(error),
        })
      )
  }

  let screen
  switch (activeScreen) {
    case "upload-processing":
      screen = (
        <UploadProcessingScreen
          caseReference={workspace.claim.id}
          finalised={caseFinalised}
          onProcessed={async () => {
            await refreshComparison()
          }}
          onContinue={() => navigate("benchmark-dashboard")}
          onOpenOntologyLibrary={() => navigate("ontology-bank")}
          onOpenManualReview={openManualReview}
        />
      )
      break
    case "document-pages":
      screen = (
        <DocumentPagesScreen onContinue={() => navigate("extracted-invoice")} />
      )
      break
    case "extracted-invoice":
      screen = (
        <ExtractedInvoiceScreen
          workspace={workspace}
          onEdit={inspectLine}
          onDecision={handleExtractionDecision}
          savingLineId={extractionSavingLineId}
          onContinue={() => navigate("calculation-checks")}
        />
      )
      break
    case "calculation-checks":
      screen = (
        <CalculationChecksScreen
          workspace={workspace}
          onContinue={() => void handleRunComparison()}
        />
      )
      break
    case "ontology-mapping":
      screen = (
        <OntologyMappingScreen
          workspace={workspace}
          onContinue={() => void handleRunComparison("price-comparison")}
          onOpenLibrary={() => navigate("ontology-bank")}
          mappingEnabled={apiMode === "api" && !caseFinalised}
          savingLineId={mappingSavingLineId}
          onMappingDecision={handleMappingDecision}
        />
      )
      break
    case "price-comparison":
      screen = (
        <ReviewFindingsScreen
          workspace={workspace}
          p90ThresholdPct={p90ThresholdPct}
          enabled={apiMode === "api" && !caseFinalised}
          processing={challengeSaving}
          onDecision={handleChallengeDecision}
          onInspect={inspectLine}
          onContinue={() => navigate("challenge-review")}
          onMappingDecision={handleMappingDecision}
          mappingSavingLineId={mappingSavingLineId}
          onProposeNewItem={handleResearch}
          researchSaving={researchSaving}
        />
      )
      break
    case "missing-items":
      screen = (
        <MissingItemsScreen
          workspace={workspace}
          enabled={apiMode === "api" && !caseFinalised}
          saving={researchSaving}
          onResearch={handleResearch}
          onApprove={handleResearchApproval}
          focusDocumentId={focusDocumentId}
        />
      )
      break
    case "challenge-review":
      screen = (
        <ApprovalScreen
          workspace={workspace}
          p90ThresholdPct={p90ThresholdPct}
          canIssue={issuanceAllowed}
          comparisonReady={comparisonReady}
          finalised={caseFinalised}
          processing={challengeSaving}
          enabled={apiMode === "api"}
          caseUnresolvedChallenges={caseUnresolvedChallenges}
          pendingInvoiceLabel={
            pendingReviewInvoice
              ? pendingReviewInvoice.invoice_number || "another invoice"
              : null
          }
          liabilityStatus={liabilityStatus}
          liabilityConfirmed={liabilityConfirmed}
          liabilityConfirming={liabilitySaving}
          onLiabilityStatusChange={changeLiabilityStatus}
          onConfirmLiability={(decision) =>
            void handleLiabilityConfirmation(decision)
          }
          onDecision={handleChallengeDecision}
          onMappingDecision={handleMappingDecision}
          mappingSavingLineId={mappingSavingLineId}
          onProposeNewItem={handleResearch}
          researchSaving={researchSaving}
          onFinalise={() => void handleChallengeFinalise()}
          onSettlement={() => setSettlementOpen(true)}
          onDownload={handleReport}
          onBackToFindings={() => navigate("price-comparison")}
          onReviewPendingInvoice={
            pendingReviewInvoice
              ? () => {
                  void handleInvoiceSelection(pendingReviewInvoice.id).then(
                    () => navigate("price-comparison")
                  )
                }
              : undefined
          }
        />
      )
      break
    case "ontology-bank":
      screen = <OntologyBankScreen workspace={workspace} />
      break
    case "benchmark-dashboard":
      screen = (
        <BenchmarkDashboardScreen
          apiMode={apiMode}
          workspace={workspace}
          challengeThreshold={p90ThresholdPct}
          onChallengeThresholdChange={setP90ThresholdPct}
          thresholdApplying={thresholdApplying}
          onOpenKnowledgeGraph={() => navigate("knowledge-graph")}
        />
      )
      break
    case "knowledge-graph":
      screen = (
        <KnowledgeGraphScreen
          apiMode={apiMode}
          caseReference={workspace.claim.id}
          challengeThreshold={p90ThresholdPct}
          onBack={() => navigate("benchmark-dashboard")}
        />
      )
      break
    case "audit-reports":
      screen = (
        <AuditReportsScreen workspace={workspace} onExport={handleReport} />
      )
      break
  }

  return (
    <>
      <AppShell
        activeScreen={activeScreen}
        onNavigate={navigate}
        issuanceAllowed={issuanceAllowed}
        liabilityStatus={liabilityStatus}
        apiMode={apiMode}
      >
        {activeScreen === "price-comparison" &&
        invoices.length > 0 &&
        !challengedInvoices.length ? (
          <div className="mb-4 rounded-lg border border-dashed bg-card px-4 py-6 text-center">
            <p className="text-sm font-medium">
              No invoices with price challenges yet
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              None of the uploaded invoices in this claim have a positive price
              challenge to review.
            </p>
          </div>
        ) : invoiceSelectorOptions.length > 1 ? (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3">
            <div>
              <p className="text-sm font-medium">
                {activeScreen === "price-comparison"
                  ? "Challenged invoices"
                  : "Uploaded invoices"}
              </p>
              <p className="text-xs text-muted-foreground">
                {activeScreen === "price-comparison"
                  ? "Only invoices with a positive price challenge are shown here."
                  : "Switch invoice details; benchmarking uses all uploaded invoices in this claim batch."}
              </p>
            </div>
            <select
              className="h-9 min-w-56 rounded-md border bg-background px-3 text-sm"
              value={workspace.invoice.id}
              disabled={comparisonSaving}
              onChange={(event) =>
                void handleInvoiceSelection(event.target.value)
              }
              aria-label="Select uploaded invoice"
            >
              {invoiceSelectorOptions.map((invoice, index) => (
                <option key={invoice.id} value={invoice.id}>
                  {invoiceDisplayLabel(invoice, index)}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        {screen}
      </AppShell>

      <LineCorrectionSheet
        key={`${selectedLine?.id ?? "line-review"}-${correctionOpen ? "open" : "closed"}`}
        line={selectedLine}
        open={correctionOpen}
        onOpenChange={setCorrectionOpen}
        onSave={(values) => void handleLineCorrection(values)}
        saving={correctionSaving}
      />
      <SettlementDialog
        key={settlementOpen ? "settlement-open" : "settlement-closed"}
        open={settlementOpen}
        onOpenChange={setSettlementOpen}
        onSave={(values) => void handleSettlement(values)}
        lines={workspace.lines.filter((line) => line.challenge > 0)}
        saving={settlementSaving}
      />
      <Toaster richColors position="bottom-right" />
    </>
  )
}

export default App
