/**
 * 三市深度区（服务端组件）
 * - 顶部段控 tab（next/link，保留 date，切 ?dmkt=cn|us|hk），当前项高亮
 * - 面板按 market 渲染：首页专用单卡异动榜
 *   CN 额外：板块热力（BoardTerrain）+ 主力资金（FundFlowBoard）
 *   US/HK：板块/资金仅 A 股 → 显一行灰字说明，不放空壳
 * - 不改变市场页继续使用的旧 MoversBoard
 */
import Link from "next/link";

import { BoardTerrain } from "@/components/board-terrain";
import { MoversPanel } from "@/components/dashboard/movers-panel";
import { FundFlowBoard } from "@/components/fund-flow-board";
import { fetchBoardHeat } from "@/lib/openbb";
import { cn } from "@/lib/utils";

type Market = "cn" | "us" | "hk";

const MARKETS: { key: Market; label: string }[] = [
  { key: "cn", label: "A股" },
  { key: "us", label: "美股" },
  { key: "hk", label: "港股" },
];

/** 段控 tab（Link 实现，避免客户端） */
function DeepTabs({ market, date }: { market: Market; date?: string }) {
  return (
    <div className="inline-flex h-8 items-center gap-1 rounded-lg bg-muted p-[3px]">
      {MARKETS.map((m) => {
        const active = m.key === market;
        const params = new URLSearchParams({ dmkt: m.key });
        if (date) params.set("date", date);
        return (
          <Link
            key={m.key}
            href={`?${params.toString()}`}
            scroll={false}
            aria-current={active ? "page" : undefined}
            className={cn(
              "inline-flex h-full items-center justify-center rounded-md px-3 text-sm font-medium whitespace-nowrap transition-all",
              active
                ? "bg-background text-foreground shadow-sm dark:bg-input/30"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {m.label}
          </Link>
        );
      })}
    </div>
  );
}

/** A 股专属：板块热力地形图 */
async function BoardHeatSection({ date }: { date?: string }) {
  const items = await fetchBoardHeat("industry", date, 15, "market_cap");
  return (
    <BoardTerrain
      items={items}
      variant="dashboard"
      date={items[0]?.snapshot_date ?? date}
    />
  );
}

/** US/HK：板块热力/资金流向暂仅 A 股 → 一行灰字说明 */
function CnOnlyNote({ label }: { label: string }) {
  return (
    <p className="text-xs text-muted-foreground">
      {label}暂仅 A 股提供
    </p>
  );
}

export async function MarketDeepSection({
  date,
  market = "cn",
}: {
  date?: string;
  market?: Market;
}) {
  const m: Market = market === "us" || market === "hk" ? market : "cn";

  return (
    <div className="space-y-4">
      {/* 段控 tab */}
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-fg-dim">三市深度</h2>
        <DeepTabs market={m} date={date} />
      </div>

      {/* 单卡四榜（类型 Tabs 在客户端切换，数据由 RSC 一次预取） */}
      <MoversPanel market={m} date={date} />

      {m === "cn" ? (
        <>
          {/* 板块热力地形图（A 股专属） */}
          <section aria-label="板块热力">
            <BoardHeatSection date={date} />
          </section>

          {/* 主力资金红绿榜（A 股专属） */}
          <section aria-label="主力资金">
            <FundFlowBoard date={date} variant="dashboard" />
          </section>
        </>
      ) : (
        <>
          <section>
            <div className="mb-3">
              <h3 className="text-sm font-medium text-fg-dim">板块热力</h3>
            </div>
            <CnOnlyNote label="板块热力" />
          </section>
          <section>
            <div className="mb-3">
              <h3 className="text-sm font-medium text-fg-dim">主力资金</h3>
            </div>
            <CnOnlyNote label="资金流向" />
          </section>
        </>
      )}
    </div>
  );
}
