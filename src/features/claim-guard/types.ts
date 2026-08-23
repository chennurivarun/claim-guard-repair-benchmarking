export const LIABILITY_STATUSES = [
  "ADMITTED",
  "DENIED",
  "SPLIT LIABILITY",
  "PENDING",
  "HUMAN REVIEW REQUIRED",
] as const

export type LiabilityStatus = (typeof LIABILITY_STATUSES)[number]

export type ScreenId =
  | "upload-processing"
  | "document-pages"
  | "extracted-invoice"
  | "calculation-checks"
  | "ontology-mapping"
  | "price-comparison"
  | "missing-items"
  | "challenge-review"
  | "ontology-bank"
  | "benchmark-dashboard"
  | "knowledge-graph"
  | "audit-reports"

export type StageId = "liability" | "documents" | "validation" | "challenge"

export type MappingStatus = "MATCH" | "NO_MATCH" | "PROVISIONAL" | "EXCLUDED"
export type ComparisonStatus =
  "CHALLENGE" | "WITHIN" | "BELOW_GATE" | "MISSING" | "EXCLUDED"
export type ChallengeReviewStatus = "review" | "approved" | "rejected"
export type SourcePrecision = "exact" | "approximate"
export type NormalisedBoundingBox = [number, number, number, number]

export interface InvoiceLineSource {
  pageId: string
  pageNumber: number
  method: string
  precision: SourcePrecision
  rawText?: string | null
  regions: Record<string, NormalisedBoundingBox>
}

export interface CalculationSourceReference {
  pageId: string
  pageNumber: number
  label: string
  bbox: NormalisedBoundingBox
  precision: SourcePrecision
}

export interface CalculationCheck {
  id: string
  type: string
  status: "pass" | "fail" | "not_applicable"
  severity: string
  expected?: number | null
  observed?: number | null
  difference?: number | null
  explanation: string
  lineId?: string | null
  sources: CalculationSourceReference[]
}

export interface ComparableObservation {
  id: string
  sourceType: "historical" | "ontology_price"
  sourceObservationId?: string | null
  description?: string | null
  priceNet?: number | null
  originalPriceNet?: number | null
  normalisedPriceNet?: number | null
  observedDate?: string | null
  weight: number
  approvalStatus?: string | null
  settlementStatus?: string | null
  provenance: Record<string, unknown>
  vehicle?: {
    make?: string | null
    model?: string | null
    variant?: string | null
    year?: number | null
  } | null
  comparabilityMetadata?: Record<string, unknown> | null
  comparableClass: string
  adjustments: Record<string, unknown>
  staleDataWarning: boolean
  eligible: boolean
  eligibilityReason?: string | null
}

export interface P90BenchmarkObservation {
  lineId: string
  invoiceId: string
  invoiceNumber: string
  invoiceDate?: string | null
  description: string
  category: string
  price: number
}

export interface P90LineBenchmark {
  category: string
  currentPrice: number
  historicalCount: number
  historicalMean: number
  p90: number
  difference: number
  percentageDifference: number
  decision: "Challenge" | "Within Benchmark"
  challenged: boolean
  explanation: string
  observations: P90BenchmarkObservation[]
  method: string
  currentInvoiceExcluded: boolean
}

export interface InvoiceLine {
  id: string
  description: string
  partNumber?: string
  kind: "Part" | "Labour" | "Service" | "Fee"
  quantity: number
  unit: string
  unitPrice: number
  currentTotal: number
  vatRate: number
  ontologyId?: string
  ontologyName?: string
  ontologyTotal?: number
  historicalMedian?: number
  historicalRange?: [number, number]
  historicalCount: number
  differenceFromOntology?: number | null
  differenceFromHistory?: number | null
  comparables?: ComparableObservation[]
  p90Benchmark?: P90LineBenchmark
  recommended?: number
  governedBenchmark?: number | null
  governedBenchmarkSource?: string | null
  governedBenchmarkFormula?: string | null
  challenge: number
  challengeResultId?: string
  challengeStatus?: ChallengeReviewStatus
  challengeApproved?: boolean
  challengeVat?: number
  mappingConfidence?: number
  mappingDecision?: string
  mappingReviewStatus?: string
  mappingReviewedBy?: string | null
  mappingReviewedAt?: string | null
  isBundled?: boolean
  bundleComponents?: Array<{
    ontology_item_id: string
    canonical_name?: string
    allocated_net?: string | null
    quantity?: string | null
    unit?: string | null
    review_required?: boolean
  }>
  evidenceConfidence?: number
  evidenceRationale?: string
  challengeStrength?: number
  extractionConfidence: number
  extractionReviewStatus?:
    "pending" | "needs_review" | "approved" | "rejected" | "corrected"
  requiresExtractionReview?: boolean
  source?: InvoiceLineSource | null
  mappingStatus: MappingStatus
  comparisonStatus: ComparisonStatus
  rationale: string
}

export interface ResearchEvidence {
  id: string
  title: string
  sourceUri: string
  capturedAt: string
  priceNet?: number | null
  approvalStatus: string
}

export interface ResearchQueueItem {
  taskId: string
  researchItemId?: string | null
  lineId: string
  lineDescription: string
  queryText: string
  status: string
  sourceAllowListVersion: string
  candidate?: string | null
  itemType?: string | null
  category?: string | null
  unit?: string | null
  partNumber?: string | null
  priceNet?: number | null
  sourceUrls: string[]
  dateChecked?: string | null
  confidence?: number | null
  rationale?: string | null
  reviewer?: string | null
  reviewedAt?: string | null
  ontologyItemId?: string | null
  evidence: ResearchEvidence[]
}

export interface OntologyBankItem {
  id: string
  code: string
  name: string
  itemType: string
  category: string
  unit: string
  referencePriceNet?: number | null
  status: string
  approvalStatus: string
  confidence: string
  observationCount: number
  source?: string | null
  sourceRef?: string | null
  effectiveDate?: string | null
  createdInVersion?: string | null
}

export interface OntologyVersionRecord {
  id?: string
  type: string
  version: string
  sequence?: number
  status: string
  published_at?: string | null
}

export interface PriceObservationRecord {
  id: string
  ontologyItemId?: string | null
  ontologyCode?: string | null
  source: string
  sourceRef?: string | null
  providerName?: string | null
  date: string
  unit: string
  priceScope?: string | null
  vatBasis?: string | null
  originalPrice?: number | null
  priceNet: number
  approvalStatus: string
}

export interface AuditEventRecord {
  id: string
  timestamp: string
  actor: string
  actor_type: string
  action: string
  entity_type: string
  entity_id?: string | null
  processing_run_id?: string | null
  correlation_id?: string | null
  before?: Record<string, unknown> | null
  after?: Record<string, unknown> | null
  payload: Record<string, unknown>
  previous_event_hash?: string | null
  event_hash?: string | null
}

export interface ClaimWorkspace {
  liability: {
    status: LiabilityStatus
    humanConfirmed: boolean
    confirmedBy?: string | null
    rationale?: string | null
    splitLiabilityPercentage?: number | null
  }
  claim: {
    id: string
    status: string
    policyNumber: string
    accidentDate: string
    accidentLocation: string
    accidentDescription: string
    damageDescription: string
    payingInsurer: string
    claimingParty: string
    insuredDriver: string
    thirdPartyDriver: string
    insuredVehicle: string
    insuredVrm: string
    thirdPartyVehicle: string
    thirdPartyVrm: string
  }
  invoice: {
    id: string
    documentId?: string
    pageNumbers?: number[]
    extractionReviewThreshold?: number
    number: string
    date: string
    garage: string
    address: string
    vehicle: string
    vehicleCategory?: {
      groupRange?: string | null
      groupCategory?: string | null
      source?: string | null
      matchStatus?: string | null
    }
    vrm: string
    mileage: number
    partsNet: number
    labourNet: number
    taxableNet: number
    vat: number
    mot: number
    netIncludingMot: number
    gross: number
  }
  lines: InvoiceLine[]
  checks?: CalculationCheck[]
  summary: {
    challengePrice: number
    challengeAmount: number
    vatImpact: number
    grossEffect: number
    challengePercentage: number
    challengeStrength: number
  }
  researchItems?: ResearchQueueItem[]
  ontologyBank?: {
    items: OntologyBankItem[]
    versions: OntologyVersionRecord[]
    priceObservations: PriceObservationRecord[]
  }
  auditEvents?: AuditEventRecord[]
  versions?: {
    ontology: string
    policy: string
    processingRunId?: string | null
    application?: string | null
  }
}

export interface ApiWorkspaceResult {
  workspace: ClaimWorkspace
  mode: "api" | "demo"
  errorMessage?: string
}
