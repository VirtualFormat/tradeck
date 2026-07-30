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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

export interface BoardItem {
  name: string;
  code?: string | null;
  change_percent: number | null;
  market_cap: number | null;
  turnover_rate: number | null;
  leader_stock: string | null;
  leader_change: number | null;
  snapshot_date?: string | null;
  source?: "eastmoney" | "ths" | null;
  size_basis?: "market_cap" | "turnover" | null;
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
  const showName = width >= (dashboard ? 34 : 48) && height >= 18;
  const showPct = width >= (dashboard ? 38 : 48) && height >= 30;
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

function formatSize(value: number | null, basis?: BoardItem["size_basis"]) {
  if (value == null) return "—";
  if (basis === "turnover") {
    return value >= 1e8 ? `${(value / 1e8).toFixed(1)}亿` : value.toLocaleString();
  }
  if (value >= 1e12) return `${(value / 1e12).toFixed(2)}万亿`;
  if (value >= 1e8) return `${(value / 1e8).toFixed(1)}亿`;
  return value.toLocaleString();
}

function pctClass(value: number | null) {
  if (value == null || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-up" : "text-down";
}

function AllBoardsDialog({
  items,
  sizeBasis,
}: {
  items: BoardItem[];
  sizeBasis?: BoardItem["size_basis"] | null;
}) {
  const rows = [...items].sort(
    (a, b) => (b.change_percent ?? -Infinity) - (a.change_percent ?? -Infinity)
  );

  return (
    <Dialog>
      <DialogTrigger
        render={
          <Button variant="ghost" size="xs" className="h-5 px-1.5 text-[10px]" />
        }
      >
        查看全部
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>全部行业板块</DialogTitle>
          <DialogDescription>
            共 {items.length} 个行业，按涨跌幅从高到低排列
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[65vh] overflow-y-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>行业</TableHead>
                <TableHead className="text-right">涨跌幅</TableHead>
                <TableHead className="text-right">
                  {sizeBasis === "turnover" ? "成交额" : "总市值"}
                </TableHead>
                <TableHead>领涨股</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((item) => (
                <TableRow key={`${item.code ?? ""}-${item.name}`}>
                  <TableCell className="font-medium">{item.name}</TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      pctClass(item.change_percent)
                    )}
                  >
                    {item.change_percent == null
                      ? "—"
                      : `${item.change_percent > 0 ? "+" : ""}${item.change_percent.toFixed(2)}%`}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    {formatSize(item.market_cap, sizeBasis)}
                  </TableCell>
                  <TableCell className="max-w-40 truncate text-muted-foreground">
                    {item.leader_stock ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function BoardTerrain({
  items,
  variant = "default",
  date,
  referenceDate,
  source,
  sizeBasis,
}: {
  items: BoardItem[];
  variant?: BoardTerrainVariant;
  date?: string;
  referenceDate?: string | null;
  source?: "eastmoney" | "ths" | null;
  sizeBasis?: "market_cap" | "turnover" | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const dashboard = variant === "dashboard";
  const chartHeight = dashboard ? (width > 0 && width < 500 ? 500 : 320) : 520;
  const snapshotDate = formatSnapshotDate(date);
  const stale = Boolean(date && referenceDate && date < referenceDate);
  const sourceLabel = source === "ths" ? "同花顺行业" : "东财行业";
  const sizeLabel = sizeBasis === "turnover" ? "面积=成交额" : "面积=总市值";
  const overviewItems = dashboard ? items.slice(0, 24) : items;

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

  const data = overviewItems
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
              板块热力&nbsp; A股 · {sourceLabel}
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
      className={cn("w-full", !dashboard && "h-[520px]")}
      style={dashboard ? { height: chartHeight } : undefined}
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

  if (!dashboard) {
    if (!date && !source && !sizeBasis) return terrain;
    return (
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-end gap-2 text-[10px] text-muted-foreground">
          {stale && (
            <Badge
              variant="secondary"
              className="h-4 rounded-sm px-1.5 text-[10px] text-warn"
            >
              数据滞后
            </Badge>
          )}
          {source && <span>{sourceLabel}</span>}
          {snapshotDate && <span>{snapshotDate}</span>}
        </div>
        {terrain}
      </div>
    );
  }

  return (
    <Card size="sm" className="gap-2 py-3">
      <CardHeader className="flex-row items-center justify-between gap-3 px-3">
        <CardTitle className="text-xs font-semibold text-fg-dim">
          板块热力&nbsp; A股 · {sourceLabel}
        </CardTitle>
        <div className="flex shrink-0 items-center gap-2 text-[10px] text-muted-foreground">
          {stale && (
            <Badge
              variant="secondary"
              className="h-4 rounded-sm px-1.5 text-[10px] text-warn"
            >
              数据滞后
            </Badge>
          )}
          <span>{sizeLabel}</span>
          <span>Top {overviewItems.length} / 共 {items.length}</span>
          <AllBoardsDialog items={items} sizeBasis={sizeBasis} />
          {snapshotDate && <span>{snapshotDate}</span>}
        </div>
      </CardHeader>
      <CardContent className="px-2">{terrain}</CardContent>
    </Card>
  );
}
