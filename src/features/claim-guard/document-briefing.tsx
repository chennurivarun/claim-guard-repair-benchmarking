import { useState } from "react"
import { InfoIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

import type { DocumentReviewBriefing } from "./document-api"

/**
 * Small info-icon button that opens the AI-generated briefing for a document
 * the pipeline could not benchmark: what it found, why it needs manual
 * review, and what to do next. Shared between the Documents screen and the
 * Manual review hub so both surfaces render the briefing identically.
 */
export function DocumentBriefingButton({
  filename,
  briefing,
}: {
  filename: string
  briefing: DocumentReviewBriefing | null | undefined
}) {
  const [open, setOpen] = useState(false)

  if (!briefing) return null

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="size-6 shrink-0 text-muted-foreground hover:text-foreground"
        aria-label={`Why ${filename} needs manual review`}
        onClick={() => setOpen(true)}
      >
        <InfoIcon className="size-4" aria-hidden />
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>What the AI found in {filename}</DialogTitle>
            <DialogDescription>{briefing.document_summary}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 text-sm">
            <div>
              <p className="font-medium">What the AI found</p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-muted-foreground">
                {briefing.content_found.length ? (
                  briefing.content_found.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))
                ) : (
                  <li>No content could be classified.</li>
                )}
              </ul>
            </div>
            <div>
              <p className="font-medium">Why it needs manual review</p>
              <p className="text-muted-foreground">{briefing.why_manual_review}</p>
            </div>
            <div>
              <p className="font-medium">Recommended action</p>
              <p className="text-muted-foreground">{briefing.recommended_action}</p>
            </div>
            <div className="flex items-center gap-2 border-t pt-3">
              <Badge variant="outline">
                {briefing.fallback ? "Automatic summary" : "AI-generated"}
              </Badge>
              <p className="text-xs text-muted-foreground">
                {briefing.fallback
                  ? "Generated automatically without an AI model — verify against the source pages."
                  : "AI-generated — verify against the source pages."}
              </p>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
