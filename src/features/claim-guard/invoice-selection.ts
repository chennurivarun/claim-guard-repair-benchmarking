import type { ClaimInvoiceSummary } from "@/lib/api"

export function challengedInvoices(
  invoices: ClaimInvoiceSummary[]
): ClaimInvoiceSummary[] {
  return invoices.filter(
    (invoice) => (invoice.challenge_review?.positive ?? 0) > 0
  )
}

export function invoiceOptionsForScreen(
  invoices: ClaimInvoiceSummary[],
  screen: "price-comparison" | "review-findings-all" | string
): ClaimInvoiceSummary[] {
  return screen === "price-comparison" ? challengedInvoices(invoices) : invoices
}

export function preferredInvoiceIdForScreen(
  invoices: ClaimInvoiceSummary[],
  screen: "price-comparison" | "review-findings-all" | string,
  currentInvoiceId: string
): string | null {
  const options = invoiceOptionsForScreen(invoices, screen)
  return options.some((invoice) => invoice.id === currentInvoiceId)
    ? currentInvoiceId
    : (options[0]?.id ?? null)
}
