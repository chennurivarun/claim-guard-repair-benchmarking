import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Toaster } from "@/components/ui/sonner"
import { AppShell, type ApiStatus } from "@/features/claim-guard/app-shell"
import {
  LineCorrectionSheet,
  type LineCorrectionValues,
} from "@/features/claim-guard/review-overlays"
import {
  AuditReportsScreen,
  MissingItemsScreen,
  OntologyBankScreen,
} from "@/features/claim-guard/screens-challenge-admin"
import { ApprovalScreen } from "@/features/claim-guard/screens-approval"
import {
  ClaimLiabilityScreen,
  DocumentPagesScreen,
  ExtractedInvoiceScreen,
} from "@/features/claim-guard/screens-liability-documents"
import {
  ChallengedInvoicesSummary,
  ReviewFindingsScreen,
} from "@/features/claim-guard/screens-review-findings"
import {
  challengedInvoices as selectChallengedInvoices,
  invoiceOptionsForScreen,
  preferredInvoiceIdForScreen,
} from "@/features/claim-guard/invoice-selection"
import { ClientIntakeScreen } from "@/features/claim-guard/screens-client-intake"
import { DocumentMappingScreen } from "@/features/claim-guard/screens-document-mapping"
import { BenchmarkDashboardScreen } from "@/features/claim-guard/screens-benchmark-dashboard"
import { KnowledgeGraphScreen } from "@/features/claim-guard/screens-knowledge-graph"
import {
  CalculationChecksScreen,
  OntologyMappingScreen,
} from "@/features/claim-guard/screens-validation"
import {
  ApiUnavailablePanel,
  ConnectingPanel,
  NoClaimsPanel,
  WorkspaceErrorPanel,
} from "@/features/claim-guard/workspace-state"
import {
  manualReviewUnavailableNotice,
  noWorkspaceNotice,
} from "@/features/claim-guard/workspace-notices"
import { documentIntelligenceViews } from "@/features/claim-guard/types"
import type {
  ClaimWorkspace,
  InvoiceLine,
  LiabilityStatus,
  ScreenId,
  WorkspaceBootstrap,
} from "@/features/claim-guard/types"
import {
  bootstrapClaimWorkspace,
  confirmLiability,
  correctInvoiceLine,
  decideExtractionLine,
  decideChallenge,
  decideLineMapping,
  downloadBlob,
  fetchClaimInvoices,
  fetchClaimWorkspace,
  finaliseClaim,
  getApiErrorMessage,
  approveResearchItem,
  requestReport,
  friendlyAiUnavailableMessage,
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
  // Nothing is assumed about the database before it answers: the workspace
  // starts empty rather than pre-filled with sample values, so a slow or
  // failed fetch can never leave invented rows on screen.
  const [workspace, setWorkspace] = useState<ClaimWorkspace | null>(null)
  const [bootstrap, setBootstrap] = useState<WorkspaceBootstrap | null>(null)
  const [activeScreen, setActiveScreen] = useState<ScreenId>("benchmark-setup")
  const [liabilityStatus, setLiabilityStatus] =
    useState<LiabilityStatus>("PENDING")
  const [liabilityConfirmed, setLiabilityConfirmed] = useState(false)
  const [selectedLine, setSelectedLine] = useState<InvoiceLine | null>(null)
  const [correctionOpen, setCorrectionOpen] = useState(false)
  const [liabilitySaving, setLiabilitySaving] = useState(false)
  const [correctionSaving, setCorrectionSaving] = useState(false)
  const [extractionSavingLineId, setExtractionSavingLineId] = useState<
    string | null
  >(null)
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
  const [challengedInvoiceDetailOpen, setChallengedInvoiceDetailOpen] =
    useState(false)
  const [selectedChallengeLineId, setSelectedChallengeLineId] = useState<
    string | null
  >(null)

  async function applyBootstrap(result: WorkspaceBootstrap) {
    setBootstrap(result)
    if (result.status !== "ready") {
      setWorkspace(null)
      setInvoices([])
      setLiabilityStatus("PENDING")
      setLiabilityConfirmed(false)
      if (result.status === "unavailable") {
        toast.error("ClaimGuard API is not ready", {
          description: `${result.message} Nothing is shown until the connection is restored.`,
        })
      }
      return
    }
    applyWorkspace(result.workspace)
    try {
      setInvoices(
        await fetchClaimInvoices(result.workspace.claim.id, p90ThresholdPct)
      )
    } catch (error) {
      setInvoices([])
      toast.error("The invoice list could not be loaded", {
        description: getApiErrorMessage(error),
      })
    }
  }

  async function connectToApi() {
    setBootstrap(null)
    await applyBootstrap(await bootstrapClaimWorkspace(p90ThresholdPct))
  }

  useEffect(() => {
    void bootstrapClaimWorkspace(p90ThresholdPct).then(applyBootstrap)
    // Only the initial p90ThresholdPct matters here; later changes are
    // handled by the dedicated threshold-refetch effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" })
  }, [activeScreen])

  // The server now computes the operational price decision (P90 policy) for
  // every line — the client no longer overlays it. Toggling the threshold
  // just refetches the workspace with the new p90_threshold_pct.
  const isFirstThresholdRender = useRef(true)
  useEffect(() => {
    if (isFirstThresholdRender.current) {
      isFirstThresholdRender.current = false
      return
    }
    if (!workspace) return
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
      .then(async (next) => {
        applyWorkspace(next)
        setInvoices(await fetchClaimInvoices(next.claim.id, p90ThresholdPct))
      })
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

  const apiStatus: ApiStatus = !bootstrap
    ? "connecting"
    : bootstrap.status === "unavailable"
      ? "unavailable"
      : "connected"
  const issuanceAllowed =
    liabilityConfirmed &&
    (liabilityStatus === "ADMITTED" || liabilityStatus === "SPLIT LIABILITY")
  const caseStatus = workspace?.claim.status.toLowerCase() ?? ""
  const caseFinalised = caseStatus === "finalised"
  const comparisonReady = caseStatus === "comparison_review"
  const caseUnresolvedChallenges = invoices.reduce(
    (total, invoice) => total + (invoice.challenge_review?.unresolved ?? 0),
    0
  )
  const clientInvoices = invoices.filter((invoice) => invoice.intake_group)
  const challengedInvoices = selectChallengedInvoices(clientInvoices)
  const pendingOntologyItems =
    workspace?.researchItems?.filter(
      (item) =>
        item.initiatedAutomatically && item.status.toLowerCase() !== "approved"
    ).length ?? 0
  const invoiceSelectorOptions = invoiceOptionsForScreen(
    clientInvoices,
    activeScreen
  )
  const screenInvoiceReady =
    activeScreen !== "price-comparison" ||
    !challengedInvoiceDetailOpen ||
    challengedInvoices.some((invoice) => invoice.id === workspace?.invoice.id)

  function applyWorkspace(nextWorkspace: ClaimWorkspace) {
    setWorkspace(nextWorkspace)
    setLiabilityStatus(nextWorkspace.liability.status)
    setLiabilityConfirmed(nextWorkspace.liability.humanConfirmed)
  }

  async function refreshWorkspace(invoiceId?: string) {
    if (!workspace) throw new Error("No claim is open.")
    const next = await fetchClaimWorkspace(
      workspace.claim.id,
      invoiceId,
      p90ThresholdPct
    )
    applyWorkspace(next)
    setInvoices(await fetchClaimInvoices(next.claim.id, p90ThresholdPct))
    return next
  }

  function navigate(screen: ScreenId) {
    if (!workspace) {
      // The screen arms below are chosen on the bootstrap status, not on
      // activeScreen, so changing activeScreen here would move nothing on
      // screen now and would silently land the user somewhere they never
      // asked for once a workspace arrives. Say why instead of doing nothing.
      const notice = noWorkspaceNotice()
      toast.info(notice.title, { description: notice.description })
      return
    }
    if (screen === "price-comparison") {
      setChallengedInvoiceDetailOpen(false)
      setSelectedChallengeLineId(null)
    }
    setActiveScreen(screen)
    const preferredInvoiceId = preferredInvoiceIdForScreen(
      [
        "document-pages",
        "extracted-invoice",
        "calculation-checks",
        "review-findings-all",
      ].includes(screen)
        ? clientInvoices.filter((invoice) => invoice.intake_group === "live")
        : clientInvoices,
      screen,
      workspace.invoice.id
    )
    if (preferredInvoiceId && preferredInvoiceId !== workspace.invoice.id) {
      void handleInvoiceSelection(preferredInvoiceId)
    }
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

  async function refreshComparison(caseReference: string, invoiceId?: string) {
    const run = await runClaimComparison(caseReference)
    await refreshWorkspace(invoiceId)
    return run
  }

  async function handleRunComparison(
    destination: ScreenId = "ontology-mapping"
  ) {
    if (!workspace) return
    setComparisonSaving(true)
    try {
      const run = await refreshComparison(
        workspace.claim.id,
        workspace.invoice.id
      )
      navigate(destination)
      toast.success("Ontology mapping and price comparison completed")
      const aiNotice = friendlyAiUnavailableMessage(run?.ai_failure_code)
      if (aiNotice) {
        toast.info("AI assistance was unavailable for this run", {
          description: aiNotice,
          id: "ai-degraded",
          duration: 9000,
        })
      }
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
    if (!workspace) return
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
      setWorkspace((current) =>
        current
          ? {
              ...current,
              liability: {
                ...current.liability,
                status: liabilityStatus,
                humanConfirmed: true,
                confirmedBy: HANDLER_ID,
                rationale: decision.rationale,
                splitLiabilityPercentage:
                  decision.splitLiabilityPercentage ?? null,
              },
            }
          : current
      )
      toast.warning("Liability saved, but the workspace could not refresh", {
        description: getApiErrorMessage(error),
      })
    } finally {
      setLiabilitySaving(false)
    }
  }

  async function handleLineCorrection(values: LineCorrectionValues) {
    if (!selectedLine || !workspace) return
    const lineTotalNet =
      Math.round(values.quantity * values.unitPrice * 100) / 100

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
      await refreshWorkspace(workspace.invoice.id)
      toast.success("Correction saved", {
        description:
          "Reprocess the invoice and rerun comparison before challenge finalisation.",
      })
    } catch (error) {
      setWorkspace((current) =>
        current
          ? {
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
            }
          : current
      )
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
    if (!workspace) return
    setExtractionSavingLineId(line.id)
    try {
      await decideExtractionLine(line.id, {
        decision,
        actor: HANDLER_ID,
        reason,
      })
      await refreshWorkspace(workspace.invoice.id)
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

  async function handleMappingDecision(
    line: InvoiceLine,
    input: Omit<MappingDecisionInput, "actor">
  ) {
    if (!workspace) throw new Error("No claim is open.")
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
    if (!workspace) throw new Error("No claim is open.")
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
    if (!workspace) return
    if (!issuanceAllowed || !comparisonReady) {
      toast.error("Challenge issuance is gated", {
        description: !issuanceAllowed
          ? "Confirm ADMITTED or SPLIT LIABILITY before finalising."
          : "Reprocess the corrected invoice and rerun comparison before finalising.",
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
        description: "The accepted-items CSV and final PDF are now available.",
      })
    } catch (error) {
      setWorkspace((current) =>
        current
          ? {
              ...current,
              claim: { ...current.claim, status: "finalised" },
              lines: current.lines.map((line) =>
                line.challenge > 0
                  ? {
                      ...line,
                      challengeApproved: true,
                      challengeStatus: "approved",
                    }
                  : line
              ),
            }
          : current
      )
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
    if (!workspace) throw new Error("No claim is open.")
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
    if (!workspace || !item.researchItemId) {
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
      await refreshWorkspace(workspace.invoice.id)
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
    if (!workspace) return
    const caseReference = workspace.claim.id
    void requestReport(format, caseReference)
      .then((blob) => {
        downloadBlob(
          blob,
          `claimguard-${caseReference}.${format === "sqlite" ? "db" : format}`
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
  if (workspace)
    switch (activeScreen) {
    case "claim-liability":
      screen = (
        <ClaimLiabilityScreen
          workspace={workspace}
          status={liabilityStatus}
          confirmed={liabilityConfirmed}
          onStatusChange={changeLiabilityStatus}
          onConfirm={(decision) => void handleLiabilityConfirmation(decision)}
          onContinue={() => navigate("upload-processing")}
          confirming={liabilitySaving}
        />
      )
      break
    case "benchmark-setup":
    case "upload-processing":
    case "document-pages":
    case "extracted-invoice":
      screen = (
        <>
          {activeScreen !== "benchmark-setup" && (
            <div className="flex items-center justify-end gap-2">
              <span className="text-xs font-medium text-muted-foreground">
                Viewing
              </span>
              <Select
                value={activeScreen}
                onValueChange={(value) => navigate(value as ScreenId)}
              >
                <SelectTrigger
                  size="sm"
                  className="w-[190px]"
                  aria-label="Document Intelligence view"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {documentIntelligenceViews.map((view) => (
                    <SelectItem key={view.id} value={view.id}>
                      {view.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {activeScreen === "document-pages" ? (
            <DocumentPagesScreen
              invoiceId={workspace.invoice.id}
              caseReference={workspace.claim.id}
              documentId={
                invoices.find((row) => row.id === workspace.invoice.id)
                  ?.document_id
              }
              onContinue={() => navigate("extracted-invoice")}
            />
          ) : activeScreen === "extracted-invoice" ? (
            <ExtractedInvoiceScreen
              workspace={workspace}
              onEdit={inspectLine}
              onDecision={handleExtractionDecision}
              savingLineId={extractionSavingLineId}
              onContinue={() => navigate("calculation-checks")}
            />
          ) : (
            <ClientIntakeScreen
              key={activeScreen}
              setup={activeScreen === "benchmark-setup"}
              onOpenManualReview={openManualReview}
              caseReference={workspace.claim.id}
              finalised={caseFinalised}
              onProcessed={async (preferredDocumentId) => {
                const latestInvoices = await fetchClaimInvoices(
                  workspace.claim.id,
                  p90ThresholdPct
                )
                const preferredInvoice = preferredDocumentId
                  ? latestInvoices.find(
                      (invoice) => invoice.document_id === preferredDocumentId
                    )
                  : undefined
                setInvoices(latestInvoices)
                await refreshWorkspace(preferredInvoice?.id)
                // The mapping step comes between upload and extracts: the
                // handler confirms which invoice each engineer assessment
                // belongs to before anything is read against those pairs.
                // Benchmark data setup builds the reference dataset and has
                // no per-claim mapping to review, so it stays where it is.
                if (activeScreen !== "benchmark-setup")
                  setActiveScreen("document-mapping")
              }}
              onContinue={() =>
                navigate(
                  activeScreen === "benchmark-setup"
                    ? "upload-processing"
                    : "document-pages"
                )
              }
            />
          )}
        </>
      )
      break
    case "document-mapping":
      screen = (
        <DocumentMappingScreen
          caseReference={workspace.claim.id}
          finalised={caseFinalised}
          // Approving runs the case-wide gap-fill sweep, which can change
          // every invoice's filled fields, so the workspace is re-read
          // before the extract tables are offered.
          onApproved={async () => {
            await refreshWorkspace()
          }}
          onContinue={() => navigate("upload-processing")}
        />
      )
      break
    case "calculation-checks":
      screen = (
        <CalculationChecksScreen
          workspace={workspace}
          onContinue={() => void handleRunComparison("review-findings-all")}
        />
      )
      break
    case "ontology-mapping":
      screen = (
        <OntologyMappingScreen
          workspace={workspace}
          onContinue={() => void handleRunComparison("price-comparison")}
          onOpenLibrary={() => navigate("ontology-bank")}
          mappingEnabled={!caseFinalised}
          savingLineId={mappingSavingLineId}
          onMappingDecision={handleMappingDecision}
        />
      )
      break
    case "price-comparison":
      screen = challengedInvoiceDetailOpen ? (
        <div className="space-y-4">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setChallengedInvoiceDetailOpen(false)
              setSelectedChallengeLineId(null)
            }}
          >
            Back to challenged invoices
          </Button>
          <ReviewFindingsScreen
            key={`${workspace.invoice.id}:${selectedChallengeLineId ?? "first"}`}
            workspace={workspace}
            initialLineId={selectedChallengeLineId}
            p90ThresholdPct={p90ThresholdPct}
            enabled={!caseFinalised}
            processing={challengeSaving}
            onDecision={handleChallengeDecision}
            onInspect={inspectLine}
            onContinue={() => navigate("challenge-review")}
            onMappingDecision={handleMappingDecision}
            mappingSavingLineId={mappingSavingLineId}
            onProposeNewItem={handleResearch}
            researchSaving={researchSaving}
          />
        </div>
      ) : (
        <ChallengedInvoicesSummary
          invoices={challengedInvoices}
          onOpenInvoice={(invoiceId, lineId) => {
            setSelectedChallengeLineId(lineId)
            setChallengedInvoiceDetailOpen(true)
            void handleInvoiceSelection(invoiceId)
          }}
        />
      )
      break
    case "review-findings-all":
      screen = (
        <>
          <Alert>
            <AlertTitle>
              {workspace.lines.some((line) => line.requiresExtractionReview)
                ? "Extraction review required"
                : workspace.lines.some(
                      (line) => line.comparisonStatus === "CHALLENGE"
                    )
                  ? "Challenge recommended"
                  : workspace.lines.some(
                        (line) => line.comparisonStatus === "MISSING"
                      ) || !workspace.lines.length
                    ? "Needs review — insufficient benchmark evidence"
                    : "No challenge recommended"}
            </AlertTitle>
            <AlertDescription>
              Review every line below and open its supporting evidence before
              making a challenge decision.
            </AlertDescription>
          </Alert>
          <ReviewFindingsScreen
            workspace={workspace}
            mode="all"
            p90ThresholdPct={p90ThresholdPct}
            enabled={!caseFinalised}
            processing={challengeSaving}
            onDecision={handleChallengeDecision}
            onInspect={inspectLine}
            onContinue={() => navigate("challenge-review")}
            onMappingDecision={handleMappingDecision}
            mappingSavingLineId={mappingSavingLineId}
            onProposeNewItem={handleResearch}
            researchSaving={researchSaving}
          />
        </>
      )
      break
    case "missing-items":
      screen = (
        <MissingItemsScreen
          workspace={workspace}
          enabled={!caseFinalised}
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
          invoices={invoices}
          canIssue={issuanceAllowed}
          comparisonReady={comparisonReady}
          finalised={caseFinalised}
          processing={challengeSaving}
          enabled
          caseUnresolvedChallenges={caseUnresolvedChallenges}
          onFinalise={() => void handleChallengeFinalise()}
          onDownload={handleReport}
          onBackToFindings={() => navigate("price-comparison")}
        />
      )
      break
    case "ontology-bank":
      screen = (
        <>
          {pendingOntologyItems > 0 ? (
            <Alert className="mb-4">
              <AlertTitle>
                {pendingOntologyItems} new scanned repair item
                {pendingOntologyItems === 1 ? " is" : "s are"} in the ontology
                bank
              </AlertTitle>
              <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <span>
                  They were learned from unmatched priced invoice lines and are
                  provisional. Review and approve them before their prices can
                  affect a challenge.
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  onClick={() => navigate("missing-items")}
                >
                  Review new items
                </Button>
              </AlertDescription>
            </Alert>
          ) : null}
          <OntologyBankScreen workspace={workspace} />
        </>
      )
      break
    case "benchmark-dashboard":
    case "in-house-benchmarks":
      screen = (
        <BenchmarkDashboardScreen
          workspace={workspace}
          challengeThreshold={p90ThresholdPct}
          onChallengeThresholdChange={setP90ThresholdPct}
          thresholdApplying={thresholdApplying}
          onOpenKnowledgeGraph={() => navigate("knowledge-graph")}
          sourceGroup={
            activeScreen === "in-house-benchmarks"
              ? "in_house"
              : "historical_claim"
          }
        />
      )
      break
    case "knowledge-graph":
      screen = (
        <KnowledgeGraphScreen
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
        apiStatus={apiStatus}
      >
        {!bootstrap ? (
          // Honestly empty: no figures, no rows, nothing that could be read as
          // data until the database has actually answered.
          <ConnectingPanel />
        ) : bootstrap.status === "unavailable" ? (
          <ApiUnavailablePanel
            message={bootstrap.message}
            onRetry={() => void connectToApi()}
          />
        ) : bootstrap.status === "no-claims" ? (
          <NoClaimsPanel onRetry={() => void connectToApi()} />
        ) : bootstrap.status === "workspace-error" ? (
          <WorkspaceErrorPanel
            caseReference={bootstrap.caseReference}
            message={bootstrap.message}
            onRetry={() => void connectToApi()}
          />
        ) : bootstrap.status === "awaiting-documents" ? (
          <div className="flex flex-col gap-6" data-testid="state-awaiting">
            <Alert>
              <AlertTitle>
                Claim {bootstrap.caseReference} has no documents yet
              </AlertTitle>
              <AlertDescription>
                Nothing has been extracted for this claim, so there is nothing
                to review. Upload a repair invoice and its engineer estimate
                below; the review screens open as soon as the first invoice has
                been read.
              </AlertDescription>
            </Alert>
            <ClientIntakeScreen
              caseReference={bootstrap.caseReference}
              setup={false}
              // Manual review is rendered from the workspace, and there is
              // none in this state, so `openManualReview` would be a silent
              // no-op on the only button the intake screen offers out of a
              // failed extraction. Report the real reason instead.
              onOpenManualReview={() => {
                const notice = manualReviewUnavailableNotice()
                toast.info(notice.title, { description: notice.description })
              }}
              finalised={false}
              onProcessed={async () => {
                await connectToApi()
              }}
              onContinue={() => void connectToApi()}
            />
          </div>
        ) : (
          <>
            {activeScreen === "price-comparison" &&
            !challengedInvoices.length ? (
              <div className="mb-4 rounded-lg border border-dashed bg-card px-4 py-6 text-center">
                <p className="text-sm font-medium">
                  No invoices with price challenges yet
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {invoices.length
                    ? "The uploaded invoices are either within the price thresholds or still waiting on manual review or repair-item matching. This page fills in as soon as a comparison finds a price worth challenging."
                    : "No invoices have been read for this claim yet. Upload documents first, then run the comparison."}
                </p>
                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => navigate("missing-items")}
                  >
                    Open Manual review
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => navigate("upload-processing")}
                  >
                    View documents
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => navigate("benchmark-dashboard")}
                  >
                    View benchmarks
                  </Button>
                </div>
              </div>
            ) : activeScreen === "price-comparison" &&
              !challengedInvoiceDetailOpen ? null : invoiceSelectorOptions.length >=
                1 &&
              [
                "document-pages",
                "extracted-invoice",
                "calculation-checks",
                "ontology-mapping",
                "review-findings-all",
                "missing-items",
              ].includes(activeScreen) ? (
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3">
                <div>
                  <p className="text-sm font-medium">
                    {activeScreen === "price-comparison"
                      ? "Review findings"
                      : "Uploaded invoices"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {activeScreen === "price-comparison"
                      ? "Only invoices with a positive price challenge are listed here."
                      : activeScreen === "review-findings-all"
                        ? "Every scanned invoice and extracted line is available in this advanced review view."
                        : "Switch invoice details; benchmarking uses all uploaded invoices in this claim batch."}
                  </p>
                </div>
                <select
                  className="h-9 min-w-56 rounded-md border bg-background px-3 text-sm"
                  value={workspace?.invoice.id}
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
            {[
              "document-pages",
              "extracted-invoice",
              "calculation-checks",
              "review-findings-all",
            ].includes(activeScreen) && !clientInvoices.length ? (
              <Alert>
                <AlertTitle>Upload a client invoice to begin</AlertTitle>
                <AlertDescription>
                  Use Benchmark data setup for reference invoices, or Document
                  Intelligence for a fresh invoice.
                </AlertDescription>
              </Alert>
            ) : screenInvoiceReady ? (
              screen
            ) : null}
          </>
        )}
      </AppShell>

      <LineCorrectionSheet
        key={`${selectedLine?.id ?? "line-review"}-${correctionOpen ? "open" : "closed"}`}
        line={selectedLine}
        open={correctionOpen}
        onOpenChange={setCorrectionOpen}
        onSave={(values) => void handleLineCorrection(values)}
        saving={correctionSaving}
      />
      <Toaster richColors position="bottom-right" />
    </>
  )
}

export default App
