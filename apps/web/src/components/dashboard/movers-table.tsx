/**
 * 首页异动榜表格
 * 使用 shadcn Table；行可点击或键盘触发 StockPreviewDialog。
 */
"use client";

import { StockPreviewTrigger } from "@/components/stock-preview-dialog";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { MoversItem, MoversType } from "@/lib/openbb";
import { cn } from "@/lib/utils";

const DISPLAY_ROWS = 6;

function formatPrice(value: number | null): string {
  if (value == null) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: value >= 1000 ? 0 : 2,
    maximumFractionDigits: value >= 1000 ? 0 : 2,
  });
}

function formatPercent(value: number | null): string {
  if (value == null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(2)}%`;
}

function formatAmount(value: number | null): string {
  if (value == null) return "—";
  if (value >= 1e12) return `${(value / 1e12).toFixed(2)}T`;
  if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(2)}K`;
  return value.toLocaleString("en-US");
}

function formatTurnover(value: number | null): string {
  return value == null ? "—" : `${(value * 100).toFixed(2)}%`;
}

function changeClass(value: number | null): string {
  if (value == null || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-up" : "text-down";
}

export function MoversTable({
  type,
  items,
}: {
  type: MoversType;
  items: MoversItem[];
}) {
  const metric =
    type === "active" ? "amount" : type === "turnover" ? "turnover" : null;
  const visibleItems = items.slice(0, DISPLAY_ROWS);
  const placeholderRows = Math.max(0, DISPLAY_ROWS - visibleItems.length);

  return (
    <Table
      className={cn(
        "text-xs",
        metric ? "min-w-[32rem]" : "min-w-[26rem]"
      )}
    >
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="h-[22px] w-full py-0 pl-4 text-[10px] text-muted-foreground">
            代码 / 名称
          </TableHead>
          <TableHead className="h-[22px] py-0 text-right text-[10px] text-muted-foreground">
            最新价
          </TableHead>
          <TableHead className="h-[22px] py-0 text-right text-[10px] text-muted-foreground">
            涨跌幅
          </TableHead>
          {metric ? (
            <TableHead className="h-[22px] py-0 pr-4 text-right text-[10px] text-muted-foreground">
              {metric === "amount" ? "估算成交额" : "估算换手"}
            </TableHead>
          ) : null}
        </TableRow>
      </TableHeader>
      <TableBody>
        {visibleItems.length > 0 ? (
          <>
            {visibleItems.map((item) => (
              <StockPreviewTrigger
                key={item.symbol}
                symbol={item.symbol}
                name={item.name}
                renderTrigger={(triggerProps) => (
                  <TableRow
                    onClick={triggerProps.onClick}
                    className="group h-6 cursor-pointer"
                  >
                    <TableCell className="h-6 min-w-44 max-w-64 py-0 pl-4">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-haspopup={triggerProps["aria-haspopup"]}
                        onClick={(event) => {
                          event.stopPropagation();
                          triggerProps.onClick(event);
                        }}
                        className="-ml-2 h-6 max-w-full justify-start gap-2 px-2 text-left focus-visible:ring-2"
                      >
                        <span className="shrink-0 text-xs font-medium text-foreground">
                          {item.symbol}
                        </span>
                        {item.name && item.name !== item.symbol ? (
                          <span className="truncate text-[11px] text-muted-foreground">
                            {item.name}
                          </span>
                        ) : null}
                      </Button>
                    </TableCell>
                    <TableCell className="h-6 py-0 text-right text-[11px] tabular-nums text-fg-dim">
                      {formatPrice(item.price)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "h-6 py-0 text-right text-xs font-medium tabular-nums",
                        changeClass(item.percent_change)
                      )}
                    >
                      {formatPercent(item.percent_change)}
                    </TableCell>
                    {metric ? (
                      <TableCell className="h-6 py-0 pr-4 text-right text-[11px] tabular-nums text-muted-foreground">
                        {metric === "amount"
                          ? formatAmount(item.amount)
                          : formatTurnover(item.turnover)}
                      </TableCell>
                    ) : null}
                  </TableRow>
                )}
              />
            ))}
            {Array.from({ length: placeholderRows }, (_, index) => (
              <TableRow
                key={`placeholder-${index}`}
                aria-hidden="true"
                className="h-6 hover:bg-transparent"
              >
                <TableCell
                  colSpan={metric ? 4 : 3}
                  className="h-6 p-0"
                />
              </TableRow>
            ))}
          </>
        ) : (
          <TableRow className="hover:bg-transparent">
            <TableCell colSpan={metric ? 4 : 3} className="h-32 p-0">
              <EmptyState
                compact
                title="暂无榜单数据"
                description="数据源恢复后将自动更新"
              />
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  );
}
