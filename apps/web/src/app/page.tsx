import Link from "next/link";
import { MarketOverview } from "@/components/market-overview";
import { StockSearch } from "@/components/stock-search";
import { PageHeader } from "@/components/page-header";
import { Flame, Newspaper, BarChart3, Star } from "lucide-react";

export default function Home() {
  return (
    <>
      <PageHeader
        title="看板"
        subtitle="Market Dashboard · Global"
        right={<StockSearch />}
      />

      {/* 快捷入口卡片 */}
      <div className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Link
          href="/heatmap"
          className="flex items-center gap-2 rounded-lg border border-border bg-panel-2 px-3 py-2.5 transition-colors hover:border-accent/50"
        >
          <Flame className="h-4 w-4 text-accent" />
          <div>
            <div className="text-xs font-medium">热力图</div>
            <div className="text-[10px] text-muted">涨跌全景</div>
          </div>
        </Link>
        <Link
          href="/news"
          className="flex items-center gap-2 rounded-lg border border-border bg-panel-2 px-3 py-2.5 transition-colors hover:border-accent/50"
        >
          <Newspaper className="h-4 w-4 text-accent" />
          <div>
            <div className="text-xs font-medium">新闻流</div>
            <div className="text-[10px] text-muted">实时资讯</div>
          </div>
        </Link>
        <Link
          href="/macro"
          className="flex items-center gap-2 rounded-lg border border-border bg-panel-2 px-3 py-2.5 transition-colors hover:border-accent/50"
        >
          <BarChart3 className="h-4 w-4 text-accent" />
          <div>
            <div className="text-xs font-medium">宏观数据</div>
            <div className="text-[10px] text-muted">CPI/利率</div>
          </div>
        </Link>
        <Link
          href="/screener"
          className="flex items-center gap-2 rounded-lg border border-border bg-panel-2 px-3 py-2.5 transition-colors hover:border-accent/50"
        >
          <Star className="h-4 w-4 text-accent" />
          <div>
            <div className="text-xs font-medium">自选筛选</div>
            <div className="text-[10px] text-muted">涨跌榜</div>
          </div>
        </Link>
      </div>

      <section>
        <h2 className="mb-3 text-sm font-medium text-fg-dim">大盘指数</h2>
        {/* @ts-expect-error Server Component */}
        <MarketOverview />
      </section>
    </>
  );
}
