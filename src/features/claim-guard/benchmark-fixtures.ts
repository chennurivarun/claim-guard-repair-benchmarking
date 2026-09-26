import type {
  AnalysisBenchmark,
  AnalysisLine,
  BenchmarkAnalysisPayload,
  BenchmarkEvidenceRow,
  ChallengeEmailDraft,
  SourceBenchmarksPayload,
} from "./benchmark-api"

/** Test fixtures shaped exactly like the API contract in
 * `client-formats/BUILD_SPEC_2026-09-18_benchmarks-and-challenges.md`.
 * The backend lane builds these endpoints in parallel; until they land, these
 * are the only place the screens meet the shapes, so every field the contract
 * names is present here -- nothing extra, nothing renamed. */

export function evidenceRow(
  overrides: Partial<BenchmarkEvidenceRow> = {}
): BenchmarkEvidenceRow {
  return {
    invoice_id: "inv-tp-1",
    invoice_number: "TP-1001",
    document_filename: "tp-1001.pdf",
    vehicle_make: "SKODA",
    vehicle_model: "KAROQ",
    registration: "A30DRY",
    description: "FRONT BUMPER",
    amount: "350.00",
    origin: "invoice",
    source_line_id: "line-tp-1",
    ...overrides,
  }
}

export const thirdPartyBenchmarks: SourceBenchmarksPayload = {
  source: "third_party",
  intake_group: "historical_claim",
  label: "Insurer Third Party invoices",
  invoice_count: 3,
  threshold_pct: "10",
  vehicle_categories: [
    { category: "SUV", invoice_count: 2, source: "lookup" },
    { category: "Hatchback", invoice_count: 0, source: "ai" },
    { category: "Unknown", invoice_count: 1, source: "unknown" },
  ],
  rows: [
    {
      vehicle_category: "SUV",
      repair_item: "Front bumper",
      repair_item_key: "front-bumper",
      line_item_type: "parts",
      observations: 3,
      p90: "412.50",
      median: "380.00",
      min: "350.00",
      max: "420.00",
      evidence: [
        evidenceRow(),
        evidenceRow({
          invoice_id: "inv-tp-2",
          invoice_number: "TP-1002",
          amount: "380.00",
          source_line_id: "line-tp-2",
        }),
        evidenceRow({
          invoice_id: "inv-tp-3",
          invoice_number: "TP-1003",
          amount: "420.00",
          origin: "engineer_assessment",
          source_line_id: "line-tp-3",
        }),
      ],
    },
    {
      vehicle_category: "Unknown",
      repair_item: "Rear door",
      repair_item_key: "rear-door",
      line_item_type: "parts",
      observations: 1,
      p90: "780.00",
      median: "780.00",
      min: "780.00",
      max: "780.00",
      evidence: [
        evidenceRow({
          invoice_id: "inv-tp-9",
          invoice_number: "TP-1009",
          vehicle_make: "ZEDMOTOR",
          vehicle_model: "Q9",
          description: "L/R DOOR",
          amount: "780.00",
          source_line_id: "line-tp-9",
        }),
      ],
    },
  ],
}

export const emptyAvivaBenchmarks: SourceBenchmarksPayload = {
  source: "aviva_dlg",
  intake_group: "in_house",
  label: "EXL/ In house Benchmark invoices",
  invoice_count: 0,
  threshold_pct: "10",
  vehicle_categories: [],
  rows: [],
}

function benchmark(overrides: Partial<AnalysisBenchmark> = {}): AnalysisBenchmark {
  return {
    available: true,
    p90: "800.00",
    observations: 3,
    above_p90: false,
    violated: false,
    difference: null,
    difference_pct: null,
    evidence: [evidenceRow()],
    ...overrides,
  }
}

const NO_BENCHMARK: AnalysisBenchmark = {
  available: false,
  p90: null,
  observations: 0,
  above_p90: false,
  violated: false,
  difference: null,
  difference_pct: null,
  evidence: [],
}

/** Six lines, deliberately delivered out of document order (an assessment
 * line first) so ordering is proved by the screen, not by the fixture. */
export const analysisLines: AnalysisLine[] = [
  {
    line_id: "ea-1",
    origin: "engineer_assessment",
    line_item_type: "labour",
    description: "STRIP/FIT BUMPER",
    repair_item: "Bumper labour",
    amount: "96.00",
    benchmarks: {
      third_party: benchmark({ p90: "100.00" }),
      aviva_dlg: benchmark({ p90: "110.00", observations: 1 }),
    },
    challenge: {
      is_challenge: false,
      level: null,
      justified_amount: null,
      challenge_amount: "0.00",
      reason: "Within both benchmarks.",
    },
  },
  {
    line_id: "inv-low",
    origin: "invoice",
    line_item_type: "parts",
    description: "L/R DOOR",
    repair_item: "Rear door",
    amount: "847.73",
    benchmarks: {
      third_party: benchmark({
        p90: "800.00",
        above_p90: true,
        difference: "47.73",
        difference_pct: "5.97",
      }),
      aviva_dlg: benchmark({ p90: "820.00", above_p90: true, difference: "27.73", difference_pct: "3.38" }),
    },
    challenge: {
      is_challenge: false,
      level: "low",
      justified_amount: null,
      challenge_amount: "0.00",
      reason: "Above the third-party P90 by 5.97%, within the 10% threshold.",
    },
  },
  {
    line_id: "inv-medium",
    origin: "invoice",
    line_item_type: "paint",
    description: "PAINT REAR DOOR",
    repair_item: "Paint",
    amount: "300.00",
    benchmarks: {
      third_party: benchmark({
        p90: "200.00",
        above_p90: true,
        violated: true,
        difference: "100.00",
        difference_pct: "50.00",
      }),
      aviva_dlg: benchmark({ p90: "320.00" }),
    },
    challenge: {
      is_challenge: true,
      level: "medium",
      justified_amount: "260.00",
      challenge_amount: "40.00",
      reason: "50/50 of £200.00 and £320.00 gives £260.00; reduction £40.00.",
    },
  },
  {
    line_id: "inv-high",
    origin: "invoice",
    line_item_type: "parts",
    description: "FRONT BUMPER",
    repair_item: "Front bumper",
    amount: "600.00",
    benchmarks: {
      third_party: benchmark({
        p90: "412.50",
        above_p90: true,
        violated: true,
        difference: "187.50",
        difference_pct: "45.45",
      }),
      aviva_dlg: benchmark({
        p90: "450.00",
        observations: 1,
        above_p90: true,
        violated: true,
        difference: "150.00",
        difference_pct: "33.33",
      }),
    },
    challenge: {
      is_challenge: true,
      level: "high",
      justified_amount: "431.25",
      challenge_amount: "168.75",
      reason: "Above both P90s; 50/50 challenge price £431.25.",
    },
  },
  {
    line_id: "ea-medium",
    origin: "engineer_assessment",
    line_item_type: "parts",
    description: "HEADLAMP",
    repair_item: "Headlamp",
    amount: "260.00",
    benchmarks: {
      third_party: benchmark({ p90: "270.00" }),
      aviva_dlg: benchmark({
        p90: "197.60",
        above_p90: true,
        violated: true,
        difference: "62.40",
        difference_pct: "31.58",
      }),
    },
    challenge: {
      is_challenge: true,
      level: "medium",
      justified_amount: "233.80",
      challenge_amount: "26.20",
      reason: "50/50 of £270.00 and £197.60 gives £233.80; reduction £26.20.",
    },
  },
  {
    line_id: "ea-none",
    origin: "engineer_assessment",
    line_item_type: "sundry",
    description: "CLIPS",
    repair_item: "Clips",
    amount: "12.00",
    benchmarks: { third_party: NO_BENCHMARK, aviva_dlg: NO_BENCHMARK },
    challenge: {
      is_challenge: false,
      level: null,
      justified_amount: null,
      challenge_amount: "0.00",
      reason: "No benchmark for this repair item in either source.",
    },
  },
]

export const benchmarkAnalysis: BenchmarkAnalysisPayload = {
  invoice: {
    id: "live-1",
    invoice_number: "LIVE-77",
    vehicle_make: "SKODA",
    vehicle_model: "KAROQ",
    vehicle_category: "SUV",
    vehicle_category_source: "lookup",
    registration: "A30DRY",
    paired_assessment_number: "D7576879",
  },
  live_invoices: [
    { id: "live-1", invoice_number: "LIVE-77", registration: "A30DRY" },
    { id: "live-2", invoice_number: "LIVE-78", registration: "B41ELK" },
  ],
  threshold_pct: "10",
  minimum_challenge_amount: "5.00",
  lines: analysisLines,
  section_breakdowns: [
    {
      invoice_id: "live-1",
      invoice_number: "LIVE-77",
      invoice_line_item_id: "rollup-parts",
      line_item_type: "parts",
      raw_category: "Total Parts",
      description: "Total Parts",
      invoice_total: "860.00",
      assessment_id: "ea-doc-1",
      assessment_total: "860.00",
      matches: true,
      difference: "0.00",
      breakdown_source: "engineer assessment",
      rows: [
        {
          id: "bd-1",
          category: "parts",
          raw_category: "Parts",
          description: "HEADLAMP",
          work_units: null,
          hours: null,
          unit_price_net: "260.00",
          total_net: "260.00",
        },
        {
          id: "bd-2",
          category: "parts",
          raw_category: "Parts",
          description: "FRONT BUMPER",
          work_units: null,
          hours: null,
          unit_price_net: "600.00",
          total_net: "600.00",
        },
      ],
    },
  ],
  totals: {
    line_count: 6,
    challenge_count: 3,
    by_level: { high: 1, medium: 2, low: 1 },
    total_challenge_amount: "234.95",
  },
}

export const templateDraft: ChallengeEmailDraft = {
  subject: "Invoice LIVE-77: 2 line items challenged",
  body: "Dear repairer,\n\nFRONT BUMPER: billed £600.00, justified £431.25.\n",
  generated_by: "template",
  lines: [analysisLines[3], analysisLines[2]],
  total_challenge_amount: "208.75",
}
