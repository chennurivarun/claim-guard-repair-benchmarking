import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"

const findings = readFileSync(
  new URL(
    "../src/features/claim-guard/screens-review-findings.tsx",
    import.meta.url
  ),
  "utf8"
)

test("challenged-line evidence is part-specific and exposes all three governed sources", () => {
  assert.match(findings, /Evidence used for \{line\.description\}/)
  assert.match(findings, /In-house benchmark P90/)
  assert.match(findings, /Historical claims P90/)
  assert.match(findings, /External reference price/)
  assert.match(findings, /View source record/)
  assert.match(findings, /Internal source reference/)
  assert.match(findings, /Synthetic demonstration evidence/)
  assert.doesNotMatch(findings, /Download source CSV/)
  assert.doesNotMatch(findings, /inHouseRepairCsvUrl/)
})
