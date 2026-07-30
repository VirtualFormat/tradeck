/**
 * 板块热力地形图（recharts Treemap，squarified 布局）
 * - 面积 ∝ 板块总市值，颜色 = 板块涨跌幅（红涨绿跌，3% 饱和）
 * - Treemap 与 ChartConfig 不契合，属 AGENTS.md「UI 强制规则」第 2 条已登记豁免组件
 * - 尺寸用 clientWidth 直接测量（不依赖 ResponsiveContainer，后台标签页也能渲染）
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { Treemap } from "recharts";

import { EmptyState } from "@/components/empty-state";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface BoardItem {
  name: string;
  change_percent: number | null;
  market_cap: number | null;
  turnover_rate: number | null;
  leader_stock: string | null;
  leader_change: number | null;
  snapshot_date?: string | null;
}

type BoardTerrainVariant = "default" | "dashboard";

/** 红涨绿跌热力色（|3%| 饱和） */
function heatColor(pct: number | null, dashboard: boolean): string {
  if (!dashboard) {
    if (pct == null) return "rgba(107,114,128,0.25)";
    const t = Math.min(Math.abs(pct) / 3, 1);
    const alpha = 0.25 + t * 0.75;
    return pct >= 0
      ? `rgba(240, 85, 107, ${alpha})`
      : `rgba(32, 205, 141, ${alpha})`;
  }

  if (pct == null) return "var(--muted)";
  const t = Math.min(Math.abs(pct) / 3, 1);
  const weight = Math.round(30 + t * 60);
  const color = pct >= 0 ? "var(--up)" : "var(--down)";
  return `color-mix(in srgb, ${color} ${weight}%, var(--muted))`;
}

function Tile(props: {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  change?: number | null;
  leader?: string | null;
  dashboard?: boolean;
}) {
  const {
    x = 0,
    y = 0,
    width = 0,
    height = 0,
    name = "",
    change,
    leader,
    dashboard = false,
  } = props;
  if (width < 6 || height < 6) return <g />;
  const showName = width >= 48 && height >= 22;
  const showPct = width >= 48 && height >= 34;
  const showLeader = !dashboard && width >= 80 && height >= 56;
  const nameY = dashboard
    ? showPct
      ? y + height / 2 - 3
      : y + height / 2 + 4
    : y + 15;
  const textX = dashboard ? x + width / 2 : x + 5;
  const textAnchor = dashboard ? "middle" : "start";
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={heatColor(change ?? null, dashboard)}
        stroke={dashboard ? "var(--card)" : "#090b11"}
        strokeWidth={dashboard ? 4 : 1.5}
        rx={dashboard ? 8 : 2}
      />
      {showName && (
        <text
          x={textX}
          y={nameY}
          fontSize={dashboard ? 10 : 11}
          fontWeight={600}
          fill={dashboard ? "var(--foreground)" : "#fff"}
          textAnchor={textAnchor}
          style={{ pointerEvents: "none", userSelect: "none" }}
        >
          {name.length * (dashboard ? 10 : 11) > width - 10
            ? `${name.slice(
                0,
                Math.max(
                  2,
                  Math.floor((width - 10) / (dashboard ? 10 : 11)) - 1
                )
              )}…`
            : name}
        </text>
      )}
      {showPct && change != null && (
        <text
          x={textX}
          y={dashboard ? y + height / 2 + 11 : y + 29}
          fontSize={10}
          fill={dashboard ? "var(--foreground)" : "rgba(255,255,255,0.85)"}
          fillOpacity={dashboard ? 0.85 : 1}
          textAnchor={textAnchor}
          style={{ pointerEvents: "none", userSelect: "none" }}
        >
          {`${change > 0 ? "+" : ""}${change.toFixed(2)}%`}
        </text>
      )}
      {showLeader && leader && (
        <text
          x={x + 5}
          y={y + 43}
          fontSize={9}
          fill="rgba(255,255,255,0.6)"
          style={{ pointerEvents: "none", userSelect: "none" }}
        >
          {leader}
        </text>
      )}
    </g>
  );
}

function formatSnapshotDate(date?: string): string | null {
  const match = date?.match(/^\d{4}-(\d{2})-(\d{2})/);
  return match ? `${match[1]}-${match[2]}` : null;
}

export function BoardTerrain({
  items,
  variant = "default",
  date,
}: {
  items: BoardItem[];
  variant?: BoardTerrainVariant;
  date?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const dashboard = variant === "dashboard";
  const chartHeight = dashboard ? 172 : 520;
  const snapshotDate = formatSnapshotDate(date);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    // clientWidth 触发同步布局，后台标签页也可读；RO 负责后续尺寸变化
    setWidth(el.clientWidth);
    const ro = new ResizeObserver((entries) => {
      setWidth(entries[0]?.contentRect.width ?? 0);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const data = items
    .filter((b) => b.market_cap && b.market_cap > 0)
    .map((b) => ({
      name: b.name,
      size: b.market_cap as number,
      change: b.change_percent,
      leader: b.leader_stock
        ? `${b.leader_stock}${
            b.leader_change != null
              ? ` ${b.leader_change > 0 ? "+" : ""}${b.leader_change.toFixed(1)}%`
              : ""
          }`
        : null,
    }));

  if (data.length === 0) {
    if (dashboard) {
      return (
        <Card size="sm" className="h-[219px] gap-2 py-3">
          <CardHeader className="px-3">
            <CardTitle className="text-xs font-semibold text-fg-dim">
              板块热力&nbsp; A股 · 东财行业
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-1 items-center justify-center px-3">
            <EmptyState compact title="等待板块数据" />
          </CardContent>
        </Card>
      );
    }
    return (
      <Card className="flex h-48 items-center justify-center">
        <EmptyState compact title="等待板块数据" />
      </Card>
    );
  }

  const terrain = (
    <div
      ref={containerRef}
      className={cn("w-full", dashboard ? "h-[172px]" : "h-[520px]")}
    >
      {width > 0 && (
        <Treemap
          data={data}
          dataKey="size"
          width={Math.round(width)}
          height={chartHeight}
          content={<Tile dashboard={dashboard} />}
        />
      )}
    </div>
  );

  if (!dashboard) return terrain;

  return (
    <Card size="sm" className="h-[219px] gap-2 py-3">
      <CardHeader className="flex-row items-center justify-between gap-3 px-3">
        <CardTitle className="text-xs font-semibold text-fg-dim">
          板块热力&nbsp; A股 · 东财行业
        </CardTitle>
        <div className="flex shrink-0 items-center gap-2 text-[10px] text-muted-foreground">
          <span>深 = 涨跌幅大</span>
          {snapshotDate && <span>{snapshotDate}</span>}
        </div>
      </CardHeader>
      <CardContent className="px-2">{terrain}</CardContent>
    </Card>
  );
}
