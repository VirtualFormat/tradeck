/**
 * 首页看板（借鉴 TickFlow Dashboard）
 * - 顶部：PageHeader + 搜索
 * - 大盘指数区（全宽）
 * - 主+侧布局：
 *   - 主：涨跌幅榜 + 热门资讯
 *   - 侧：宏观速览
 */
import { MarketOverview } from "@/components/market-overview";
import { StockSearch } from "@/components/stock-search";
import { PageHeader } from "@/components/page-header";
import { MoversBoard, TopNews } from "@/components/movers-board";
import { MacroSnapshot } from "@/components/macro-snapshot";

export default function Home() {
  return (
    <>
      <PageHeader
        title="看板"
        subtitle="Market Dashboard · Global"
        right={<StockSearch />}
      />

      {/* 大盘指数（全宽） */}
      <section className="mb-6">
        <h2 className="mb-3 text-sm font-medium text-fg-dim">大盘指数</h2>
        {/* @ts-expect-error Server Component */}
        <MarketOverview />
      </section>

      {/* 主+侧布局（借鉴 TickFlow grid-cols-[1fr_20rem]） */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_18rem]">
        {/* 主区 */}
        <div className="space-y-6">
          {/* 涨跌幅榜 */}
          {/* @ts-expect-error Server Component */}
          <MoversBoard />

          {/* 热门资讯 */}
          {/* @ts-expect-error Server Component */}
          <TopNews />
        </div>

        {/* 侧栏 */}
        <div className="space-y-6">
          {/* 宏观速览 */}
          {/* @ts-expect-error Server Component */}
          <MacroSnapshot />
        </div>
      </div>
    </>
  );
}
