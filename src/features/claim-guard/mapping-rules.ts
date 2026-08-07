import type { InvoiceLine } from "./types"

export function isMappingApproved(
  line: Pick<
    InvoiceLine,
    | "mappingStatus"
    | "mappingReviewStatus"
    | "mappingConfidence"
    | "ontologyId"
  >
) {
  if (!line.ontologyId || line.mappingStatus === "EXCLUDED") return false

  const automaticallyApproved = (line.mappingConfidence ?? 0) > 95
  const requiresReview = /REVIEW|PENDING|PROVISIONAL/i.test(
    line.mappingReviewStatus ?? ""
  )

  return (
    automaticallyApproved ||
    (line.mappingStatus === "MATCH" && !requiresReview)
  )
}
