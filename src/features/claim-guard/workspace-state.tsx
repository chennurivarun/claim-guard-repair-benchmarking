import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"

/**
 * The panels shown when there is no claim workspace to review.
 *
 * Each one states what is actually true — the database has not answered yet,
 * it holds no claims, or it could not be reached — and shows nothing else. No
 * sample claim, invoice or price is ever rendered in place of missing data.
 */

export function ConnectingPanel() {
  return (
    <Alert data-testid="state-connecting">
      <AlertTitle>Connecting to Price Benchmarking Model TP Repair</AlertTitle>
      <AlertDescription>
        Loading claims, invoices and benchmark data. Nothing is displayed until
        the database answers.
      </AlertDescription>
    </Alert>
  )
}

export function ApiUnavailablePanel({
  message,
  onRetry,
}: {
  message: string
  onRetry: () => void
}) {
  return (
    <Alert variant="destructive" data-testid="state-unavailable">
      <AlertTitle>Price Benchmarking Model TP Repair API is unavailable</AlertTitle>
      <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span>
          {message} No claim, invoice or price data is shown, because none could
          be read.
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="shrink-0"
          onClick={onRetry}
        >
          Retry connection
        </Button>
      </AlertDescription>
    </Alert>
  )
}

export function WorkspaceErrorPanel({
  caseReference,
  message,
  onRetry,
}: {
  caseReference: string
  message: string
  onRetry: () => void
}) {
  return (
    <Alert variant="destructive" data-testid="state-workspace-error">
      <AlertTitle>Claim {caseReference} could not be opened</AlertTitle>
      <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span>
          {message} Nothing is shown for this claim, because its review data
          could not be built.
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="shrink-0"
          onClick={onRetry}
        >
          Try again
        </Button>
      </AlertDescription>
    </Alert>
  )
}

/**
 * The database holds no claim, so no upload screen has anything to upload
 * into. The panel must offer the way forward itself — an instruction to
 * upload with no upload control on the page is a dead end — so it starts the
 * claim (the same empty claim `claimguard-setup` opens) on one click.
 */
export function NoClaimsPanel({
  onStart,
  onRetry,
  starting,
}: {
  onStart: () => void
  onRetry: () => void
  starting: boolean
}) {
  return (
    <Alert data-testid="state-no-claims">
      <AlertTitle>No claims yet</AlertTitle>
      <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span>
          The database holds no claims. Start a new claim to open the Third
          party invoice upload screen, then upload a repair invoice and its
          engineer assessment — every screen fills in from the uploaded
          documents and nothing else.
        </span>
        <span className="flex shrink-0 gap-2">
          <Button
            type="button"
            size="sm"
            onClick={onStart}
            disabled={starting}
          >
            {starting ? "Starting a new claim…" : "Start a new claim"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onRetry}
            disabled={starting}
          >
            Check again
          </Button>
        </span>
      </AlertDescription>
    </Alert>
  )
}
