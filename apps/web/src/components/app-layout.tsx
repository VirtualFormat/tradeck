/**
 * 应用布局：左侧栏 + 主区（借鉴 TickFlow）
 * 侧边栏：Logo + 导航 + 指数小卡片
 * 主区：页面切换动画 + 内容
 */
import Link from "next/link";
import { LayoutDashboard, Search, Newspaper, BarChart3, Star, Flame } from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "看板", icon: LayoutDashboard },
  { href: "/screener", label: "自选 / 筛选", icon: Star },
  { href: "/heatmap", label: "热力图", icon: Flame },
  { href: "/news", label: "新闻流", icon: Newspaper },
  { href: "/macro", label: "宏观数据", icon: BarChart3 },
];

// 指数小卡片（侧栏底部，借鉴 TickFlow SidebarIndexQuotes）
const SIDEBAR_INDICES = [
  { symbol: "^GSPC", name: "标普500" },
  { symbol: "^IXIC", name: "纳指" },
  { symbol: "000001.SS", name: "上证" },
];

async function fetchSidebarIndices() {
  const BACKEND_API_URL =
    process.env.BACKEND_API_URL ?? "http://localhost:8080";
  try {
    const results = await Promise.all(
      SIDEBAR_INDICES.map(async (idx) => {
        const end = new Date();
        const start = new Date(end.getTime() - 7 * 24 * 60 * 60 * 1000);
        const fmt = (d: Date) => d.toISOString().slice(0, 10);
        const res = await fetch(
          `${BACKEND_API_URL}/api/indices?symbol=${encodeURIComponent(
            idx.symbol
          )}&start_date=${fmt(start)}&end_date=${fmt(end)}`,
          { headers: { Accept: "application/json" } }
        );
        if (!res.ok) return { ...idx, price: null, changePct: null };
        const data = await res.json();
        if (!Array.isArray(data) || data.length === 0)
          return { ...idx, price: null, changePct: null };
        const last = data[data.length - 1];
        const prev = data.length > 1 ? data[data.length - 2] : last;
        return {
          ...idx,
          price: last.close,
          changePct: prev.close > 0 ? (last.close - prev.close) / prev.close : 0,
        };
      })
    );
    return results;
  } catch {
    return SIDEBAR_INDICES.map((idx) => ({ ...idx, price: null, changePct: null }));
  }
}

function SidebarIndexQuotes() {
  return (
    <div className="border-t border-border px-3 py-2">
      <SidebarIndices />
    </div>
  );
}

async function SidebarIndices() {
  const indices = await fetchSidebarIndices();
  return (
    <div className="space-y-1">
      {indices.map((idx) => {
        const up = (idx.changePct ?? 0) >= 0;
        return (
          <div key={idx.symbol} className="flex items-center justify-between text-[10px]">
            <span className="text-muted">{idx.name}</span>
            {idx.price != null ? (
              <span className={`tab-nums ${up ? "text-up" : "text-down"}`}>
                {idx.price.toFixed(0)}
                <span className="ml-1 text-[9px]">
                  {up ? "▲" : "▼"}
                  {idx.changePct != null
                    ? `${Math.abs(idx.changePct * 100).toFixed(1)}%`
                    : ""}
                </span>
              </span>
            ) : (
              <span className="text-muted">—</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-bg text-fg">
      {/* 侧边栏（14rem，借鉴 TickFlow） */}
      <aside className="fixed inset-y-0 left-0 z-30 flex w-56 flex-col border-r border-border bg-panel">
        {/* Logo */}
        <div className="border-b border-border px-4 py-4">
          <Link href="/" className="block">
            <span className="text-base font-bold tracking-wide">tradeck</span>
            <span className="ml-1 text-[9px] uppercase tracking-[0.2em] text-muted">
              v0.1
            </span>
          </Link>
        </div>

        {/* 导航 */}
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className="mb-0.5 flex items-center gap-2 rounded-md px-3 py-2 text-xs text-fg-dim transition-colors hover:bg-panel-2 hover:text-fg"
              >
                <Icon className="h-3.5 w-3.5" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* 侧栏底部指数小卡片 */}
        <SidebarIndexQuotes />
      </aside>

      {/* 主区 */}
      <main className="flex-1 pl-56">
        <div className="mx-auto max-w-7xl px-6 py-6">
          {children}
        </div>
      </main>
    </div>
  );
}
