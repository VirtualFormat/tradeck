"use client";

/**
 * 量化工作台
 * 路由：/quant
 * 数据全部经 Next 代理路由（/api/quant/*），不直连 quant 容器
 * Tab 经 ?tab= URL 参数驱动（侧边栏二级入口 deep-link 到指定 Tab）
 */
import { Suspense, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { EmptyState } from "@/components/empty-state";
import { AIGenerateTab } from "@/components/quant/ai-generate-tab";
import { BacktestTab } from "@/components/quant/backtest-tab";
import { MiningTab } from "@/components/quant/mining-tab";
import { ScreenTab } from "@/components/quant/screen-tab";
import {
  defaultParamValues,
  type ParamValues,
  type StrategyDef,
} from "@/components/quant/types";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

// 合法 Tab 值（URL 参数白名单，非法值回退 backtest）
const TAB_VALUES = ["backtest", "screen", "ai", "mining"] as const;
type TabValue = (typeof TAB_VALUES)[number];

function normalizeTab(raw: string | null): TabValue {
  return (TAB_VALUES as readonly string[]).includes(raw ?? "")
    ? (raw as TabValue)
    : "backtest";
}

function QuantPageInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tab = normalizeTab(searchParams.get("tab"));

  const [strategies, setStrategies] = useState<StrategyDef[]>([]);
  const [strategiesLoading, setStrategiesLoading] = useState(true);
  // 回测 / 扫描各自维护策略选择与参数值，互不干扰
  const [btStrategyId, setBtStrategyId] = useState("");
  const [btParams, setBtParams] = useState<ParamValues>({});
  const [scStrategyId, setScStrategyId] = useState("");
  const [scParams, setScParams] = useState<ParamValues>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/quant/strategies", {
          cache: "no-store",
        });
        const list: StrategyDef[] = res.ok ? await res.json() : [];
        if (cancelled) return;
        setStrategies(list);
        if (list.length > 0) {
          setBtStrategyId(list[0].id);
          setBtParams(defaultParamValues(list[0]));
          setScStrategyId(list[0].id);
          setScParams(defaultParamValues(list[0]));
        }
      } catch {
        if (!cancelled) setStrategies([]);
      } finally {
        if (!cancelled) setStrategiesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /** 切换策略时把参数表单重置为新策略 schema 的默认值 */
  const makeStrategyChange = useCallback(
    (setId: (id: string) => void, setParams: (v: ParamValues) => void) =>
      (id: string) => {
        setId(id);
        setParams(
          defaultParamValues(strategies.find((s) => s.id === id) ?? null)
        );
      },
    [strategies]
  );

  /** 切换 Tab 时写回 URL（侧边栏 deep-link 与页内 Tab 保持同步，可分享/后退） */
  const handleTabChange = useCallback(
    (value: string) => {
      router.replace(`${pathname}?tab=${value}`, { scroll: false });
    },
    [router, pathname]
  );

  return (
    <main className="mx-auto w-full max-w-7xl space-y-4 p-4 md:p-6">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold">量化工作台</h1>
        <p className="text-sm text-muted-foreground">
          策略回测、选股扫描、AI 策略生成与因子挖掘
        </p>
      </div>

      <Tabs value={tab} onValueChange={handleTabChange}>
        <TabsList>
          <TabsTrigger value="backtest">策略回测</TabsTrigger>
          <TabsTrigger value="screen">选股扫描</TabsTrigger>
          <TabsTrigger value="ai">AI 策略生成</TabsTrigger>
          <TabsTrigger value="mining">因子挖掘</TabsTrigger>
        </TabsList>

        <TabsContent value="backtest" className="pt-4">
          {strategiesLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : strategies.length === 0 ? (
            <EmptyState
              title="暂无可用策略"
              description="quant 服务未返回策略列表，请确认 quant 容器已启动"
              compact
            />
          ) : (
            <BacktestTab
              strategies={strategies}
              strategiesLoading={strategiesLoading}
              strategyId={btStrategyId}
              onStrategyChange={makeStrategyChange(setBtStrategyId, setBtParams)}
              paramValues={btParams}
              onParamValuesChange={setBtParams}
            />
          )}
        </TabsContent>

        <TabsContent value="screen" className="pt-4">
          {strategiesLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : strategies.length === 0 ? (
            <EmptyState
              title="暂无可用策略"
              description="quant 服务未返回策略列表，请确认 quant 容器已启动"
              compact
            />
          ) : (
            <ScreenTab
              strategies={strategies}
              strategiesLoading={strategiesLoading}
              strategyId={scStrategyId}
              onStrategyChange={makeStrategyChange(setScStrategyId, setScParams)}
              paramValues={scParams}
              onParamValuesChange={setScParams}
            />
          )}
        </TabsContent>

        <TabsContent value="ai" className="pt-4">
          <AIGenerateTab />
        </TabsContent>

        <TabsContent value="mining" className="pt-4">
          <MiningTab />
        </TabsContent>
      </Tabs>
    </main>
  );
}

export default function QuantPage() {
  // useSearchParams 需 Suspense 包裹（Next.js App Router 要求）
  return (
    <Suspense fallback={<Skeleton className="m-6 h-96 w-full max-w-7xl" />}>
      <QuantPageInner />
    </Suspense>
  );
}
