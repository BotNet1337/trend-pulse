import { describe, expect, it } from "vitest"
import { renderToStaticMarkup } from "react-dom/server"

import {
  DegradedTile,
  KpiCards,
  MetricSkeleton,
  PlatformBreakdownChart,
  PublicationsByStatusChart,
  SuccessRateGauge,
} from "../../../src/features/analytics/ui"
import { DashboardEmptyState, DashboardErrorState } from "../../../src/features/analytics/ui/dashboard-states"
import type { Channel } from "../../../src/entities/channel"

const render = (node: Parameters<typeof renderToStaticMarkup>[0]): string =>
  renderToStaticMarkup(node)

const channel: Channel = {
  id: "ch-b",
  workspaceId: "ws-1",
  userId: "u-1",
  platform: "linkedin",
  name: "Acme Page",
  subject: "li:1",
  status: "active",
  state: "active",
  meta: { displayName: "Acme Page" },
  connectedAt: "2026-01-01T00:00:00Z",
  expiresAt: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
}

describe("KpiCards", () => {
  it("renders KPI values from data", () => {
    const html = render(
      <KpiCards
        data={{ totalPosts: 128, activeChannels: 5, upcomingPublications: 14 }}
      />,
    )
    expect(html).toContain("Постов за период")
    expect(html).toContain("128")
    expect(html).toContain("5")
    expect(html).toContain("14")
  })

  it("renders skeletons when loading", () => {
    const html = render(<KpiCards data={null} loading />)
    expect(html).toContain("metric-skeleton")
  })
})

describe("PublicationsByStatusChart", () => {
  it("renders an SVG with mock rows", () => {
    const html = render(
      <PublicationsByStatusChart
        rows={[{ day: "2026-05-09", status: "published", total: 12 }]}
      />,
    )
    expect(html).toContain("publications-chart")
    expect(html).toContain("Опубликовано")
  })

  it("renders an empty message with no rows", () => {
    const html = render(<PublicationsByStatusChart rows={[]} />)
    expect(html).toContain("Нет публикаций")
  })
})

describe("SuccessRateGauge", () => {
  it("renders the rounded percent and counts", () => {
    const html = render(
      <SuccessRateGauge
        data={{ published: 241, failed: 15, total: 256, successRate: 0.94 }}
      />,
    )
    expect(html).toContain("94%")
    expect(html).toContain("241")
    expect(html).toContain("15")
  })
})

describe("PlatformBreakdownChart", () => {
  it("resolves channel_id → name from workspace channels", () => {
    const html = render(
      <PlatformBreakdownChart
        rows={[{ platform: "linkedin", channelId: "ch-b", total: 86 }]}
        channels={[channel]}
      />,
    )
    expect(html).toContain("Acme Page")
    expect(html).toContain("86")
  })

  it("renders an empty message with no rows", () => {
    const html = render(<PlatformBreakdownChart rows={[]} channels={[]} />)
    expect(html).toContain("Нет данных")
  })
})

describe("states", () => {
  it("DegradedTile is soft + retryable (not an error)", () => {
    const html = render(<DegradedTile title="KPI" onRetry={() => {}} />)
    expect(html).toContain("metric-degraded")
    expect(html).toContain("Данные временно недоступны")
    expect(html).toContain("Обновить")
  })

  it("MetricSkeleton renders a placeholder", () => {
    expect(render(<MetricSkeleton />)).toContain("metric-skeleton")
  })

  it("DashboardErrorState shows retry", () => {
    const html = render(
      <DashboardErrorState message="boom" onRetry={() => {}} />,
    )
    expect(html).toContain("dashboard-error")
    expect(html).toContain("Не удалось загрузить дашборд")
    expect(html).toContain("Повторить")
  })

  it("DashboardEmptyState shows onboarding CTAs", () => {
    const html = render(
      <DashboardEmptyState
        onConnectChannel={() => {}}
        onCreatePost={() => {}}
      />,
    )
    expect(html).toContain("dashboard-empty")
    expect(html).toContain("Подключить канал")
    expect(html).toContain("Создать первый пост")
  })
})
