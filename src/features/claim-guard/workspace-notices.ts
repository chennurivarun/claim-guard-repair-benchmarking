/**
 * What the app says when a screen cannot be opened.
 *
 * Kept apart from `workspace-state.tsx` so that file exports only
 * components (the react-refresh rule), and because these messages are
 * raised as toasts from handlers rather than rendered as panels.
 */

/** A short, true explanation of why something could not be opened. */
export interface WorkspaceUnavailableNotice {
  title: string
  description: string
}

/**
 * Why a review screen cannot be opened while no claim workspace is loaded.
 *
 * Every review screen is rendered from the workspace, so changing the active
 * screen without one shows nothing — and silently moves the user somewhere
 * they never asked for once a workspace does arrive. Refusing and saying why
 * is the honest alternative to a dead click.
 */
export function noWorkspaceNotice(): WorkspaceUnavailableNotice {
  return {
    title: "No claim data is loaded",
    description:
      "The review screens are built from an extracted invoice, and none has been read yet. They open on their own as soon as one has.",
  }
}

/**
 * Why Manual review cannot be opened for a document that is flagged for
 * review on a claim that has nothing extracted yet.
 *
 * The button is the only route the intake screen offers out of a failed
 * extraction, so it must not be wired to a handler that does nothing.
 */
export function manualReviewUnavailableNotice(): WorkspaceUnavailableNotice {
  return {
    title: "Manual review cannot open yet",
    description:
      "This document could not be read, and Manual review is itself built from an extracted invoice. Reprocess the document, or upload one that can be read, and the review screens open automatically.",
  }
}
