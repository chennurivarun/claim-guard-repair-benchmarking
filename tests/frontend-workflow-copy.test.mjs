import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8")

const overview = read("../src/features/claim-guard/screens-overview.tsx")
const findings = read("../src/features/claim-guard/screens-review-findings.tsx")
const approval = read("../src/features/claim-guard/screens-approval.tsx")
const challengeAdmin = read(
  "../src/features/claim-guard/screens-challenge-admin.tsx"
)
const app = read("../src/App.tsx")
const benchmarkDashboard = read(
  "../src/features/claim-guard/screens-benchmark-dashboard.tsx"
)
const appShell = read("../src/features/claim-guard/app-shell.tsx")

test("primary workflow distinguishes payable price from challenge amount", () => {
  const primaryWorkflow = [
    overview,
    findings,
    approval,
    challengeAdmin,
    app,
  ].join("\n")

  assert.doesNotMatch(primaryWorkflow, />Challenge Price</)
  assert.doesNotMatch(primaryWorkflow, /Accept .*Challenge Price/)
  assert.doesNotMatch(primaryWorkflow, /Edit Challenge Price/)
  assert.match(overview, /Proposed payable net/)
  assert.match(findings, /Supported net price/)
  assert.match(approval, /Challenge amount/)
})

test("provisional mappings cannot be mistaken for actionable findings", () => {
  assert.match(
    findings,
    /Provisional finding: repair item match needs approval/
  )
  assert.match(findings, /Approve repair item match first/)
  assert.match(findings, /disabled=.*!mappingApproved/s)
  assert.match(approval, /pendingMappings\.length === 0/)
  assert.match(approval, /Approve repair item matches first/)
  assert.match(overview, /Repair item approval required/)
})

test("successful batch processing refreshes ontology mapping and price comparison", () => {
  assert.match(
    app,
    /async function refreshComparison\(invoiceId\?: string\)[\s\S]*await runClaimComparison\(workspace\.claim\.id\)[\s\S]*return refreshWorkspace\(invoiceId\)/
  )
  assert.match(
    app,
    /onProcessed=\{async \(\) => \{[\s\S]*await refreshComparison\(\)[\s\S]*\}\}/
  )
})

test("benchmark summary totals and sorts the same challenged invoice rows", () => {
  assert.match(
    benchmarkDashboard,
    /item\.exceptions\.reduce\(\(sum, row\) => sum \+ row\.difference, 0\)/
  )
  assert.match(
    benchmarkDashboard,
    /sortHeader\("Total challenge", "totalChallenge"\)/
  )
  assert.match(benchmarkDashboard, /sortedBenchmarks\.map\(\(item\) =>/)
  assert.match(
    benchmarkDashboard,
    /preciseMoney\(totalChallengeAmount\(item\)\)/
  )
})

test("challenge decision is retained under advanced tools only", () => {
  const primaryBlock = appShell.match(
    /const primaryNavigation = \[[\s\S]*?\] satisfies/
  )?.[0]
  const advancedBlock = appShell.match(
    /const administration = \[[\s\S]*?\] satisfies/
  )?.[0]

  assert.ok(primaryBlock)
  assert.ok(advancedBlock)
  assert.doesNotMatch(primaryBlock, /challenge-review/)
  assert.match(advancedBlock, /challenge-review/)
  assert.match(appShell, /open=\{administrationOpen \|\| advancedToolActive\}/)
})
