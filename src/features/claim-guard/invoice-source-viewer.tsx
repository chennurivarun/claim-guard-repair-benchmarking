import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  ExpandIcon,
  LocateFixedIcon,
  MinusIcon,
  PlusIcon,
  RotateCcwIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { useIsMobile } from "@/hooks/use-mobile"
import { cn } from "@/lib/utils"

import {
  documentApiErrorMessage,
  documentImageUrl,
  fetchDocumentPages,
  type DocumentPageRecord,
} from "./document-api"
import type { CalculationSourceReference } from "./types"

export function SourceReviewLayout({
  open,
  onOpenChange,
  viewer,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  viewer: ReactNode
  children: ReactNode
}) {
  const mobile = useIsMobile()

  if (!open) return children
  if (mobile) {
    return (
      <>
        {children}
        <Sheet open onOpenChange={onOpenChange}>
          <SheetContent className="w-full p-0 sm:max-w-none">
            <SheetHeader className="sr-only">
              <SheetTitle>Invoice source</SheetTitle>
              <SheetDescription>
                Verify extracted data against the invoice.
              </SheetDescription>
            </SheetHeader>
            {viewer}
          </SheetContent>
        </Sheet>
      </>
    )
  }

  return (
    <ResizablePanelGroup
      orientation="horizontal"
      className="h-[calc(100vh-10rem)] min-h-[640px] max-h-[900px] rounded-xl border"
    >
      <ResizablePanel defaultSize={55} minSize={38}>
        <div className="h-full overflow-x-hidden overflow-y-auto p-5">
          {children}
        </div>
      </ResizablePanel>
      <ResizableHandle withHandle />
      <ResizablePanel defaultSize={45} minSize={30}>
        {viewer}
      </ResizablePanel>
    </ResizablePanelGroup>
  )
}

export function InvoiceSourceViewer({
  caseReference,
  documentId,
  pageNumbers = [],
  sources,
}: {
  caseReference: string
  documentId?: string
  pageNumbers?: number[]
  sources: CalculationSourceReference[]
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const firstHighlightRef = useRef<HTMLDivElement>(null)
  const [pages, setPages] = useState<DocumentPageRecord[]>([])
  const [pageId, setPageId] = useState<string | null>(
    sources[0]?.pageId ?? null
  )
  const [zoom, setZoom] = useState(100)
  const [loading, setLoading] = useState(true)
  const [imageLoading, setImageLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retryKey, setRetryKey] = useState(0)
  const pageNumberKey = pageNumbers.join(",")

  useEffect(() => {
    let active = true
    const allowedPageNumbers = pageNumberKey
      ? pageNumberKey.split(",").map(Number)
      : []
    fetchDocumentPages(caseReference)
      .then((records) => {
        if (!active) return
        const filtered = records.filter(
          (page) =>
            (!documentId || page.document_id === documentId) &&
            (!allowedPageNumbers.length ||
              allowedPageNumbers.includes(page.page_number))
        )
        setPages(filtered)
        setPageId((current) => current ?? filtered[0]?.id ?? null)
        setError(null)
      })
      .catch((reason) => active && setError(documentApiErrorMessage(reason)))
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
  }, [caseReference, documentId, pageNumberKey, retryKey])

  const page = pages.find((item) => item.id === pageId) ?? pages[0]
  const pageIndex = page ? pages.findIndex((item) => item.id === page.id) : -1
  const visibleSources = useMemo(
    () => sources.filter((source) => source.pageId === page?.id),
    [page?.id, sources]
  )

  function stepPage(offset: number) {
    const next = pages[pageIndex + offset]
    if (next) {
      setImageLoading(true)
      setPageId(next.id)
    }
  }

  function selectPage(nextPageId: string) {
    setImageLoading(true)
    setPageId(nextPageId)
  }

  function revealSelectedSource() {
    window.requestAnimationFrame(() => {
      const container = scrollRef.current
      const highlight = firstHighlightRef.current
      if (!container || !highlight) return
      container.scrollTo({
        top: Math.max(0, highlight.offsetTop - container.clientHeight / 2),
        behavior: "smooth",
      })
    })
  }

  return (
    <div
      ref={rootRef}
      className="flex h-full min-h-[560px] flex-col bg-muted/30"
    >
      <div className="flex flex-wrap items-center gap-2 border-b bg-background p-3">
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="icon-sm"
            disabled={pageIndex <= 0}
            onClick={() => stepPage(-1)}
            aria-label="Previous invoice page"
          >
            <ChevronLeftIcon />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            disabled={pageIndex < 0 || pageIndex >= pages.length - 1}
            onClick={() => stepPage(1)}
            aria-label="Next invoice page"
          >
            <ChevronRightIcon />
          </Button>
        </div>
        <Select value={page?.id ?? ""} onValueChange={selectPage}>
          <SelectTrigger size="sm" aria-label="Invoice page">
            <SelectValue placeholder="Page" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {pages.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  Page {item.page_number} of {pages.length}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <div className="ml-auto flex items-center gap-1">
          <Button
            variant="outline"
            size="icon-sm"
            onClick={() => setZoom((value) => Math.max(50, value - 25))}
            aria-label="Zoom out"
          >
            <MinusIcon />
          </Button>
          <span className="w-12 text-center text-xs tabular-nums">{zoom}%</span>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={() => setZoom((value) => Math.min(200, value + 25))}
            aria-label="Zoom in"
          >
            <PlusIcon />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={() => setZoom(100)}
            aria-label="Fit invoice to width"
          >
            <LocateFixedIcon />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={() => {
              setZoom(100)
              setPageId(sources[0]?.pageId ?? pages[0]?.id ?? null)
            }}
            aria-label="Reset invoice viewer"
          >
            <RotateCcwIcon />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={() => void rootRef.current?.requestFullscreen()}
            aria-label="View invoice full screen"
          >
            <ExpandIcon />
          </Button>
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-auto p-4">
        {loading ? (
          <div className="mx-auto max-w-xl space-y-3">
            <Skeleton className="aspect-[0.707] w-full" />
            <p className="text-center text-sm text-muted-foreground">
              Loading invoice page
            </p>
          </div>
        ) : error || !page ? (
          <Alert variant="destructive" className="mx-auto max-w-md">
            <AlertTitle>Invoice page unavailable</AlertTitle>
            <AlertDescription className="space-y-3">
              <p>
                {error ?? "No rendered invoice page is linked to this invoice."}
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setLoading(true)
                  setRetryKey((value) => value + 1)
                }}
              >
                Retry
              </Button>
            </AlertDescription>
          </Alert>
        ) : (
          <div
            className="mx-auto"
            style={{
              width: `${zoom}%`,
              minWidth: zoom > 100 ? 640 : undefined,
            }}
          >
            <div className="relative overflow-hidden rounded-md bg-white shadow-sm ring-1 ring-black/10">
              {imageLoading && (
                <Skeleton className="absolute inset-0 z-10 aspect-[0.707] w-full" />
              )}
              <img
                key={`${page.id}-${retryKey}`}
                src={documentImageUrl(page.image_url)}
                alt={`Invoice page ${page.page_number}`}
                className="block h-auto w-full"
                loading="lazy"
                onLoad={() => {
                  setImageLoading(false)
                  setError(null)
                  revealSelectedSource()
                }}
                onError={() => {
                  setImageLoading(false)
                  setError(
                    `Page ${page.page_number} image could not be loaded.`
                  )
                }}
              />
              {visibleSources.map((source, index) => {
                const [x0, y0, x1, y1] = source.bbox
                return (
                  <div
                    ref={index === 0 ? firstHighlightRef : undefined}
                    key={`${source.label}-${index}`}
                    className={cn(
                      "absolute border-2 bg-yellow-300/35",
                      source.precision === "approximate" &&
                        "border-dashed border-amber-600 bg-amber-300/25",
                      source.precision === "exact" && "border-yellow-500"
                    )}
                    style={{
                      left: `${x0 * 100}%`,
                      top: `${y0 * 100}%`,
                      width: `${(x1 - x0) * 100}%`,
                      height: `${(y1 - y0) * 100}%`,
                    }}
                  >
                    <span className="absolute -top-6 left-0 rounded bg-foreground px-1.5 py-0.5 text-[10px] font-medium whitespace-nowrap text-background">
                      {source.precision === "approximate"
                        ? `Approximate · ${source.label}`
                        : source.label}
                    </span>
                  </div>
                )
              })}
            </div>
            {!sources.length && (
              <p className="mt-3 text-center text-sm text-muted-foreground">
                Source location unavailable for this selection.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
