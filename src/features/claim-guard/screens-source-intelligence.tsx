import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  fetchClaimExtracts,
  getApiErrorMessage,
  type ClaimExtractsPayload,
} from "@/lib/api"

import type { IntakeGroup } from "./document-api"
import { ExtractsSection } from "./extracts-section"
import { DocumentMappingScreen } from "./screens-document-mapping"
import { INTAKE_GROUP_LABELS } from "./source-scope"

/** Source-scoped mapping review and extracted evidence. Evidence remains visible
 * before approval so the handler can inspect documents before confirming pairs. */
export function SourceIntelligenceScreen({
  caseReference,
  intakeGroup,
  finalised,
  onApproved,
  onOpenBenchmarks,
}: {
  caseReference: string
  intakeGroup: IntakeGroup
  finalised: boolean
  onApproved?: () => Promise<void> | void
  /** Benchmark computation for a reference source; Benchmark analysis for
   * the new invoice. */
  onOpenBenchmarks: () => void
}) {
  const [approved, setApproved] = useState(false)
  const [extracts, setExtracts] = useState<ClaimExtractsPayload | null>(null)
  const [extractsLoading, setExtractsLoading] = useState(true)
  const [extractsError, setExtractsError] = useState<string | null>(null)
  /** Bumped after every approval: approving runs the gap-fill sweep, which
   * can change what the extract tables show. */
  const [extractsVersion, setExtractsVersion] = useState(0)
  const label = INTAKE_GROUP_LABELS[intakeGroup]

  useEffect(() => {
    let active = true
    void fetchClaimExtracts(caseReference, intakeGroup)
      .then((payload) => {
        if (!active) return
        setExtracts(payload)
        setExtractsError(null)
      })
      .catch((e) => {
        if (!active) return
        setExtracts(null)
        setExtractsError(getApiErrorMessage(e))
      })
      .finally(() => {
        if (active) setExtractsLoading(false)
      })
    return () => {
      active = false
    }
  }, [approved, caseReference, intakeGroup, extractsVersion])

  const handleApproved = useCallback(async () => {
    setExtractsLoading(true)
    setExtractsVersion((current) => current + 1)
    await onApproved?.()
  }, [onApproved])

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3">
        <div>
          <p className="text-sm font-medium">{label}</p>
          <p className="text-xs text-muted-foreground">
            Document intelligence · the mapping and the extracts for this
            source only.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onOpenBenchmarks}>
          {intakeGroup === "live"
            ? "Go to Benchmark analysis"
            : "Go to Benchmark computation"}
        </Button>
      </div>

      <DocumentMappingScreen
        caseReference={caseReference}
        intakeGroup={intakeGroup}
        finalised={finalised}
        onApproved={handleApproved}
        onApprovalChange={setApproved}
      />

      {!approved && (
        <Card className="border-dashed">
          <CardHeader>
            <CardTitle>Review extracted documents and proposed pairs</CardTitle>
            <CardDescription>
              Extracted values are shown below before approval so you can inspect
              both documents. Approve mapping after checking the proposed pairs.
              Missing or ambiguous matches remain in manual review.
            </CardDescription>
          </CardHeader>
        </Card>
      )}
      <ExtractsSection
        extracts={extracts}
        loading={extractsLoading}
        error={extractsError}
        scopeLabel={label}
      />
    </>
  )
}
