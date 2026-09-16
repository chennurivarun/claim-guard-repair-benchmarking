import { describe, expect, it } from "vitest"

import {
  NO_EXPANSION_CHOICES,
  isRowExpanded,
  toggleRowExpansion,
} from "./row-expansion"

// The extracts tables' defaults are recomputed from props on every render
// while the user's expansion state survives them, and Document Intelligence
// refetches after every batch and after every page correction. An invoice
// whose line count crosses `AUTO_EXPAND_LINE_LIMIT`, or whose breakdown gains
// or loses rows between two fetches, therefore flips its own default -- and
// the old "store the departures from the default" scheme turned that flip
// into a silent inversion of the reader's own choice.

const KEY = "invoice-1"

describe("a reader's expansion choice survives a default that flips", () => {
  it("keeps a row the reader collapsed collapsed when the default becomes open", () => {
    // 30 lines with a resolving breakdown: the row auto-expands.
    const opened = isRowExpanded(NO_EXPANSION_CHOICES, KEY, true)
    expect(opened).toBe(true)

    // The reader folds it away.
    const choices = toggleRowExpansion(NO_EXPANSION_CHOICES, KEY, true)
    expect(isRowExpanded(choices, KEY, true)).toBe(false)

    // A refetch pushes the invoice past the auto-expand limit, so the default
    // is now `false`. Under "departures from the default" this re-opened the
    // row the reader had just closed.
    expect(isRowExpanded(choices, KEY, false)).toBe(false)
  })

  it("keeps a row the reader opened open when the default becomes collapsed", () => {
    // A long invoice: not pre-expanded.
    const choices = toggleRowExpansion(NO_EXPANSION_CHOICES, KEY, false)
    expect(isRowExpanded(choices, KEY, false)).toBe(true)

    // A page correction drops the line count back under the limit, so the
    // default is now `true`. Under "departures from the default" this closed
    // the row the reader had just opened.
    expect(isRowExpanded(choices, KEY, true)).toBe(true)
  })

  it("still both opens a collapsed row and closes an opened one", () => {
    let choices = toggleRowExpansion(NO_EXPANSION_CHOICES, KEY, false)
    expect(isRowExpanded(choices, KEY, false)).toBe(true)
    choices = toggleRowExpansion(choices, KEY, false)
    expect(isRowExpanded(choices, KEY, false)).toBe(false)
    choices = toggleRowExpansion(choices, KEY, false)
    expect(isRowExpanded(choices, KEY, false)).toBe(true)
  })

  it("leaves untouched rows on whatever the current default says", () => {
    const choices = toggleRowExpansion(NO_EXPANSION_CHOICES, KEY, true)
    expect(isRowExpanded(choices, "invoice-2", true)).toBe(true)
    expect(isRowExpanded(choices, "invoice-2", false)).toBe(false)
  })

  it("does not mutate the map it was handed", () => {
    const before = toggleRowExpansion(NO_EXPANSION_CHOICES, KEY, true)
    toggleRowExpansion(before, KEY, true)
    expect(isRowExpanded(before, KEY, true)).toBe(false)
    expect(NO_EXPANSION_CHOICES.size).toBe(0)
  })
})
