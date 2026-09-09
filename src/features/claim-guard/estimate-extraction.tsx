import { useEffect, useState } from "react"
import {
  fetchClaimInvoices,
  fetchEngineerAssessments,
  getApiErrorMessage,
  type ClaimInvoiceSummary,
  type EngineerAssessmentPayload,
} from "@/lib/api"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { DataCard } from "./shared"

export function EstimateExtraction({
  caseReference,
  invoiceId,
}: {
  caseReference: string
  invoiceId: string
}) {
  const [data, setData] = useState<{
    invoice?: ClaimInvoiceSummary
    estimates: EngineerAssessmentPayload[]
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let active = true
    void Promise.all([
      fetchClaimInvoices(caseReference),
      fetchEngineerAssessments(caseReference),
    ])
      .then(([invoices, estimates]) => {
        if (active)
          setData({
            invoice: invoices.find((i) => i.id === invoiceId),
            estimates: estimates.filter(
              (e) => e.paired_invoice_id === invoiceId
            ),
          })
      })
      .catch((e) => {
        if (active) setError(getApiErrorMessage(e))
      })
    return () => {
      active = false
    }
  }, [caseReference, invoiceId])
  if (error)
    return (
      <Alert variant="destructive">
        <AlertTitle>Estimate sources unavailable</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    )
  if (!data)
    return (
      <p className="text-sm text-muted-foreground">Loading document sources…</p>
    )
  return (
    <DataCard
      title="Invoice and engineer estimate"
      description="Missing vehicle fields are filled from a safely linked estimate. Existing invoice values remain authoritative; both sources are shown for review."
    >
      {!data.estimates.length ? (
        <p className="p-4 text-sm text-muted-foreground">
          No engineer estimate is linked to this invoice. Invoice-only review
          remains available; an unmatched estimate requires an identifier check.
        </p>
      ) : (
        data.estimates.map((estimate) => {
          const rows = [
            [
              "make",
              "Make",
              data.invoice?.vehicle?.make,
              estimate.vehicle_make,
            ],
            [
              "model",
              "Model",
              data.invoice?.vehicle?.model,
              estimate.vehicle_model,
            ],
            [
              "registration",
              "Registration",
              data.invoice?.vehicle?.registration,
              estimate.registration,
            ],
            ["vin", "VIN", data.invoice?.vehicle?.vin, estimate.vin],
            [
              "mileage",
              "Mileage",
              data.invoice?.vehicle?.mileage,
              estimate.mileage,
            ],
          ] as const
          return (
            <div key={estimate.id} className="space-y-3 p-4">
              <p className="text-sm font-medium">
                Estimate {estimate.assessment_number || estimate.id} ·{" "}
                {estimate.pair_reasons.join("; ")}
              </p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Field</TableHead>
                    <TableHead>Invoice</TableHead>
                    <TableHead>Engineer estimate</TableHead>
                    <TableHead>Used value</TableHead>
                    <TableHead>Source</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map(([key, label, value, estimateValue]) => (
                    <TableRow key={key}>
                      <TableCell>{label}</TableCell>
                      <TableCell>
                        {estimate.field_sources?.[key]
                          ? "Not present"
                          : (value ?? "Not extracted")}
                      </TableCell>
                      <TableCell>{estimateValue ?? "Not extracted"}</TableCell>
                      <TableCell>{value ?? "Not extracted"}</TableCell>
                      <TableCell>
                        {estimate.field_sources?.[key]?.label ||
                          (value != null ? "Repair invoice" : "Missing")}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Estimate operation</TableHead>
                    <TableHead>Estimate net</TableHead>
                    <TableHead>Invoice net</TableHead>
                    <TableHead>Comparison</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {estimate.operations.map((op) => (
                    <TableRow key={op.id}>
                      <TableCell>{op.description}</TableCell>
                      <TableCell>{op.total_net ?? "Not extracted"}</TableCell>
                      <TableCell>
                        {op.variances[0]?.invoice_amount ?? "Unmatched"}
                      </TableCell>
                      <TableCell>
                        {op.variances[0]?.explanation ||
                          "No matching invoice line"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )
        })
      )}
    </DataCard>
  )
}
