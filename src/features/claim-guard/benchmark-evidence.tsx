import { CircleHelpIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { categorySourceLabel, isUnknownCategory, money } from "./benchmark-analysis-rows"
import type {
  BenchmarkEvidenceRow,
  LineOrigin,
  VehicleCategorySource,
} from "./benchmark-api"

/** Which document a row was read from. Every benchmark and analysis row
 * shows it, because the two documents combine on these screens and the
 * reader has to be able to tell which one a figure came from. */
export function OriginBadge({ origin }: { origin: LineOrigin }) {
  return origin === "invoice" ? (
    <Badge variant="outline">Invoice</Badge>
  ) : (
    <Badge
      variant="outline"
      className="border-sky-300 text-sky-700 dark:border-sky-900 dark:text-sky-300"
    >
      Engineer assessment
    </Badge>
  )
}

/** A vehicle category and where it came from. `Unknown` is drawn as an
 * unknown -- dashed, with a question mark and the reason -- so it can never
 * be read as a vehicle class like SUV or Hatchback. */
export function VehicleCategoryBadge({
  category,
  source,
  showSource = true,
}: {
  category: string
  source?: VehicleCategorySource | null
  showSource?: boolean
}) {
  if (isUnknownCategory(category, source)) {
    return (
      <span
        data-category-unknown="true"
        className="inline-flex flex-wrap items-center gap-1.5"
      >
        <Badge
          variant="outline"
          className="gap-1 border-dashed border-amber-400 text-amber-700 dark:text-amber-300"
        >
          <CircleHelpIcon aria-hidden />
          Unknown category
        </Badge>
        {showSource ? (
          <span className="text-xs text-muted-foreground">
            make and model not recognised
          </span>
        ) : null}
      </span>
    )
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Badge variant="secondary">{category}</Badge>
      {showSource && source ? (
        <span className="text-xs text-muted-foreground">
          {categorySourceLabel(source)}
        </span>
      ) : null}
    </span>
  )
}

/** The contributing rows behind one P90. */
export function EvidenceTable({ rows }: { rows: BenchmarkEvidenceRow[] }) {
  if (!rows.length)
    return (
      <p className="text-sm text-muted-foreground">
        No contributing rows: this source holds no observation for this repair
        item in this vehicle category.
      </p>
    )
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Invoice</TableHead>
          <TableHead>Vehicle</TableHead>
          <TableHead>Registration</TableHead>
          <TableHead>Description</TableHead>
          <TableHead>From</TableHead>
          <TableHead className="text-right">Amount</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={`${row.invoice_id}:${row.source_line_id}`}>
            <TableCell>
              <span className="font-medium">
                {row.invoice_number ?? "Not printed"}
              </span>
              {row.document_filename ? (
                <span className="block text-xs text-muted-foreground">
                  {row.document_filename}
                </span>
              ) : null}
            </TableCell>
            <TableCell>
              {[row.vehicle_make, row.vehicle_model].filter(Boolean).join(" ") ||
                "—"}
            </TableCell>
            <TableCell>{row.registration ?? "—"}</TableCell>
            <TableCell>{row.description}</TableCell>
            <TableCell>
              <OriginBadge origin={row.origin} />
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {money(row.amount)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
