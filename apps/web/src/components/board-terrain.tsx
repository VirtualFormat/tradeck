/**
 * 板块热力地形图（recharts Treemap，squarified 布局）
 * - 面积 ∝ 板块总市值，颜色 = 板块涨跌幅（红涨绿跌，3% 饱和）
 * - Treemap 与 ChartConfig 不契合，属 AGENTS.md「UI 强制规则」第 2 条已登记豁免组件
 * - 尺寸用 clientWidth 直接测量（不依赖 ResponsiveContainer，后台标签页也能渲染）
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { Treemap } from "recharts";

import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";

export interface BoardItem {
  name: string;
  change_percent: number | null;
  market_cap: number | null;
  turnover_rate: number | null;
  leader_stock: string | null;
  leader_change: number | null;
}

/** 红涨绿跌热力色（|3%| 饱和） */
function heatColor(pct: number | null): string {
  if (pct == null) return "rgba(107,114,128,0.25)";
  const t = Math.min(Math.abs(pct) / 3, 1);
  const alpha = 0.25 + t * 0.75;
  return pct >= 0
    ? `rgba(240, 85, 107, ${alpha})`
    : `rgba(32, 205, 141, ${alpha})`;
}

function Tile(props: {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  change?: number | null;
  leader?: string | null;
}) {
  const { x = 0, y = 0, width = 0, height = 0, name = "", change, leader } = props;
  if (width < 6 || height < 6) return <g />;
  const showName = width >= 56 && height >= 24;
  const showPct = width >= 56 && height >= 40;
  const showLeader = width >= 80 && height >= 56;
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={heatColor(change ?? null)}
        stroke="#090b11"
        strokeWidth={1.5}
        rx={2}
      />
      {showName && (
        <text
          x={x + 5}
          y={y + 15}
          fontSize={11}
          fontWeight={600}
          fill="#fff"
          style={{ pointerEvents: "none", userSelect: "none" }}
        >
          {name.length * 11 > width - 10
            ? `${name.slice(0, Math.max(2, Math.floor((width - 10) / 11) - 1))}…`
            : name}
        </text>
      )}
      {showPct && change != null && (
        <text
          x={x + 5}
          y={y + 29}
          fontSize={10}
          fill="rgba(255,255,255,0.85)"
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

export function BoardTerrain({ items }: { items: BoardItem[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

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
    return (
      <Card className="flex h-48 items-center justify-center">
        <EmptyState compact title="等待板块数据" />
      </Card>
    );
  }

  return (
    <div ref={containerRef} className="h-[520px] w-full">
      {width > 0 && (
        <Treemap
          data={data}
          dataKey="size"
          width={Math.round(width)}
          height={520}
          content={<Tile />}
        />
      )}
    </div>
  );
}
