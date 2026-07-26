/**
 * A 股市场页
 * 路由：/markets/cn
 * 板块：指数条 / 板块热力地形图（行业/概念）/ 舆情热度榜 / 资金红绿榜 / 个股榜单 / A股新闻
 */
import { Suspense } from "react";
import { MarketOverview } from "@/components/market-overview";
import { MoversBoard, TopNews } from "@/components/movers-board";
import { BoardTerrain, type BoardItem } from "@/components/board-terrain";
import { BoardTypeTabs } from "@/components/board-type-tabs";
import { BoardSentimentBoard } from "@/components/board-sentiment-board";
import { FundFlowBoard } from "@/components/fund-flow-board";
import { MarketBreadthPanel } from "@/components/market-breadth-panel";
import { StockSearch } from "@/components/stock-search";
import { DatePicker } from "@/components/date-picker";
import { RefreshButton } from "@/components/refresh-button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";

function CardSkeleton() {
  return <Skeleton className="h-40 w-full rounded-lg" />;
}

async function fetchBoardHeat(type: string, date?: string): Promise<BoardItem[]> {
  const BACKEND_API_URL =
    process.env.BACKEND_API_URL ?? "http://localhost:8080";
  try {
    const dateQuery = date ? `&date=${date}` : "";
    const res = await fetch(
      `${BACKEND_API_URL}/api/boards/heat?type=${type}&limit=80${dateQuery}`,
      { headers: { Accept: "application/json" } }
    );
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

function Legend() {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex flex-wrap items-center gap-4 text-[10px] text-muted-foreground">
          <span>图例：</span>
          <span className="flex items-center gap-1">
            <span
              className="inline-block h-3 w-3 rounded"
              style={{ backgroundColor: "rgba(240,85,107,1)" }}
            />
            涨（越深涨幅越大）
          </span>
          <span className="flex items-center gap-1">
            <span
              className="inline-block h-3 w-3 rounded"
              style={{ backgroundColor: "rgba(32,205,141,1)" }}
            />
            跌（越深跌幅越大）
          </span>
          <span className="flex items-center gap-1">
            <span
              className="inline-block h-3 w-3 rounded"
              style={{ backgroundColor: "rgba(107,114,128,0.25)" }}
            />
            无数据
          </span>
          <span className="ml-4">面积 = 板块总市值 · 颜色按 ±3% 饱和</span>
        </div>
      </CardContent>
    </Card>
  );
}

async function BoardHeatSection({ type, date }: { type: string; date?: string }) {
  const items = await fetchBoardHeat(type, date);
  return <BoardTerrain items={items} />;
}

export default async function CnMarketPage({
  searchParams,
}: {
  searchParams: Promise<{ board?: string; date?: string }>;
}) {
  const { board, date } = await searchParams;
  const boardType = board === "concept" ? "concept" : "industry";

  return (
    <div className="space-y-6 px-4 lg:px-6">
      {/* 顶部操作栏 */}
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">A股</h1>
        <StockSearch />
        <DatePicker />
        <RefreshButton />
        {date && (
          <Badge variant="secondary" className="bg-accent/20 text-accent">
            快照模式：{date}
          </Badge>
        )}
      </div>

      {/* A股指数 */}
      <Suspense fallback={<Skeleton className="h-24 w-full rounded-lg" />}>
        <MarketOverview market="cn" />
      </Suspense>

      {/* 市场宽度（乐咕全市场涨跌家数） */}
      <section>
        <div className="mb-3 flex items-center gap-3">
          <h2 className="text-sm font-medium text-fg-dim">市场宽度</h2>
        </div>
        <Suspense fallback={<CardSkeleton />}>
          <MarketBreadthPanel />
        </Suspense>
      </section>

      {/* 板块热力地形图（从 /heatmap 迁入） */}
      <section>
        <div className="mb-3 flex items-center gap-3">
          <h2 className="text-sm font-medium text-fg-dim">板块热力地形图</h2>
          <BoardTypeTabs />
        </div>
        <div className="mb-3">
          <Legend />
        </div>
        <Suspense
          key={`${boardType}-${date ?? ""}`}
          fallback={<Skeleton className="h-[520px] w-full rounded-lg" />}
        >
          <BoardHeatSection type={boardType} date={date} />
        </Suspense>
      </section>

      {/* 舆情热度榜 */}
      <Suspense
        key={`bs-${boardType}-${date ?? ""}`}
        fallback={<CardSkeleton />}
      >
        <BoardSentimentBoard type={boardType} date={date} />
      </Suspense>

      {/* 资金红绿榜 */}
      <Suspense fallback={<CardSkeleton />}>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <FundFlowBoard date={date} />
        </div>
      </Suspense>

      {/* 个股榜单 */}
      <Suspense fallback={<CardSkeleton />}>
        <MoversBoard market="cn" />
      </Suspense>

      {/* A股新闻 */}
      <Suspense fallback={<CardSkeleton />}>
        <TopNews market="cn" />
      </Suspense>
    </div>
  );
}
