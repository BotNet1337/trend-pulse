import { describe, expect, it, vi, afterEach } from "vitest"

import {
  channelsLabel,
  displayName,
  formatRelativeRu,
  initial,
} from "@/features/moderation/ui/lib"
import { moderationQueueQueryKey } from "@/features/moderation/queue/model"
import { moderationDetailQueryKey } from "@/features/moderation/detail/model"

describe("channelsLabel — RU pluralisation", () => {
  it("uses the singular form for 1", () => {
    expect(channelsLabel(1)).toBe("1 целевой канал")
  })
  it("uses the few form for 2–4", () => {
    expect(channelsLabel(2)).toBe("2 целевых канала")
    expect(channelsLabel(3)).toBe("3 целевых канала")
  })
  it("uses the many form for 0, 5+, and teens", () => {
    expect(channelsLabel(0)).toBe("0 целевых каналов")
    expect(channelsLabel(5)).toBe("5 целевых каналов")
    expect(channelsLabel(11)).toBe("11 целевых каналов")
    expect(channelsLabel(21)).toBe("21 целевой канал")
  })
})

describe("initial / displayName", () => {
  it("uppercases the first letter, '?' for empty", () => {
    expect(initial("acme")).toBe("A")
    expect(initial(null)).toBe("?")
    expect(initial("   ")).toBe("?")
  })
  it("falls back to a label for empty names", () => {
    expect(displayName("Acme", "WS")).toBe("Acme")
    expect(displayName(null, "WS")).toBe("WS")
    expect(displayName("  ", "WS")).toBe("WS")
  })
})

describe("formatRelativeRu", () => {
  afterEach(() => vi.useRealTimers())

  it("formats recent and day-old timestamps", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-06-07T12:00:00Z"))
    expect(formatRelativeRu("2026-06-07T11:58:00Z")).toBe("2 мин назад")
    expect(formatRelativeRu("2026-06-07T09:00:00Z")).toBe("3 ч назад")
    expect(formatRelativeRu("2026-06-06T12:00:00Z")).toBe("вчера")
  })

  it("returns empty string for an invalid date", () => {
    expect(formatRelativeRu("not-a-date")).toBe("")
  })
})

describe("query keys", () => {
  it("queue key embeds offset/limit and matches across SSR + client", () => {
    expect(moderationQueueQueryKey({ offset: 0, limit: 100 })).toEqual([
      "",
      "moderation",
      "queue",
      0,
      100,
    ])
  })
  it("detail key embeds the request id", () => {
    expect(moderationDetailQueryKey("req-9")).toEqual([
      "",
      "moderation",
      "{id}",
      "req-9",
    ])
  })
})
