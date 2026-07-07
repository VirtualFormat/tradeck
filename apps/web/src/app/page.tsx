/**
 * 首页看板（借鉴 TickFlow Dashboard）
 * - 大盘指数（全宽）
 * - 主+侧布局：
 *   - 主：涨幅榜/跌幅榜/活跃榜 Top 10 + 热门资讯
 *   - 侧：宏观速览 + 大宗商品 + 国债收益率
 */
import { MarketOverview } from "@/components/market-overview";
import { StockSearch } from "@/components/stock-search";
import { PageHeader } from "@/components/page-header";
import { MoversBoard, TopNews } from "@/components/movers-board";
import { MacroSnapshot } from "@/components/macro-snapshot";
import { CommoditiesBoard } from "@/components/commodities-board";
import { TreasuryBoard } from "@/components/treasury-board";

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

      {/* 主+侧布局 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_18rem]">
        {/* 主区 */}
        <div className="space-y-6">
          {/* 涨跌幅榜 + 活跃榜 */}
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

          {/* 大宗商品 */}
          {/* @ts-expect-error Server Component */}
          <CommoditiesBoard />

          {/* 国债收益率 */}
          {/* @ts-expect-error Server Component */}
          <TreasuryBoard />
        </div>
      </div>
    </>
  );
}
