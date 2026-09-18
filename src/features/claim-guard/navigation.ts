import {
  BarChart3Icon,
  ClipboardCheckIcon,
  FileClockIcon,
  FileTextIcon,
  FolderSearch2Icon,
  GaugeIcon,
  LayoutDashboardIcon,
  LibraryBigIcon,
  LinkIcon,
  ScaleIcon,
  SearchCheckIcon,
  Share2Icon,
  UploadIcon,
} from "lucide-react"

import type { ScreenId } from "./types"

/** The sidebar's information architecture, kept out of `app-shell.tsx` so
 * the fast-refresh lint rule keeps that file to components, and so it can be
 * asserted on its own. Locked by `app-shell.test.ts`. */

export interface NavigationItem {
  id: ScreenId
  label: string
  icon: typeof LayoutDashboardIcon
}

/** The left navigation Neha dictated on the 17 Sep walkthrough: "two major
 * headings. Third party insured invoices and Aviva DLG invoices. Under every
 * heading … upload documents … document intelligence … benchmark
 * computation", then a third heading, "upload new invoice", whose last step
 * is benchmark analysis. */
export const navigationSections: Array<{
  id: string
  label: string
  items: NavigationItem[]
}> = [
  {
    id: "third-party",
    label: "Third party insured invoices",
    items: [
      { id: "tp-upload", label: "Upload documents", icon: UploadIcon },
      { id: "tp-intelligence", label: "Document intelligence", icon: FileTextIcon },
      { id: "tp-benchmarks", label: "Benchmark computation", icon: BarChart3Icon },
    ],
  },
  {
    id: "aviva-dlg",
    label: "Aviva DLG invoices",
    items: [
      { id: "dlg-upload", label: "Upload documents", icon: UploadIcon },
      { id: "dlg-intelligence", label: "Document intelligence", icon: FileTextIcon },
      { id: "dlg-benchmarks", label: "Benchmark computation", icon: BarChart3Icon },
    ],
  },
  {
    id: "new-invoice",
    label: "Upload new invoice",
    items: [
      { id: "new-invoice-upload", label: "Upload", icon: UploadIcon },
      {
        id: "new-invoice-intelligence",
        label: "Document intelligence",
        icon: FileTextIcon,
      },
      { id: "benchmark-analysis", label: "Benchmark analysis", icon: ScaleIcon },
    ],
  },
]

/** Every screen that predates her structure. Moved here on 18 Sep rather
 * than deleted: they still work, and some (the audit trail, the external
 * price library) are the only way to reach what they show. */
export const advancedTools: NavigationItem[] = [
  { id: "benchmark-setup", label: "Benchmark data setup", icon: LibraryBigIcon },
  {
    id: "upload-processing",
    label: "Document Intelligence (whole claim)",
    icon: FileTextIcon,
  },
  { id: "document-mapping", label: "Mapping review", icon: LinkIcon },
  {
    id: "benchmark-dashboard",
    label: "Repair Price Benchmarking",
    icon: BarChart3Icon,
  },
  { id: "in-house-benchmarks", label: "In-house Benchmark", icon: BarChart3Icon },
  { id: "price-comparison", label: "Challenged invoices", icon: SearchCheckIcon },
  { id: "challenge-review", label: "Challenge decision", icon: ClipboardCheckIcon },
  { id: "knowledge-graph", label: "Knowledge graph", icon: Share2Icon },
  { id: "claim-liability", label: "Claim & liability", icon: ClipboardCheckIcon },
  { id: "review-findings-all", label: "Review findings", icon: SearchCheckIcon },
  {
    id: "ontology-mapping",
    label: "Repair item matching",
    icon: FolderSearch2Icon,
  },
  { id: "missing-items", label: "Manual review", icon: GaugeIcon },
  { id: "ontology-bank", label: "External price library", icon: LibraryBigIcon },
  { id: "audit-reports", label: "Audit trail", icon: FileClockIcon },
]

/** Sub-views that have no entry of their own highlight the entry they are
 * reached from. */
const SUB_VIEW_PARENTS: Partial<Record<ScreenId, ScreenId>> = {
  "document-pages": "upload-processing",
  "extracted-invoice": "upload-processing",
  "calculation-checks": "upload-processing",
}

export function activeEntryId(activeScreen: ScreenId): ScreenId {
  return SUB_VIEW_PARENTS[activeScreen] ?? activeScreen
}
