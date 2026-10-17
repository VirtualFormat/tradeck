"use client";

import { PencilSimpleIcon, TrashIcon } from "@phosphor-icons/react";

import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import {
  currencyPrefix,
  getQuoteFreshness,
  inferInstrumentIdentity,
  type NativeCurrency,
  type QuoteFreshness,
  type WatchlistTableProps,
  type WorkbenchQuote,
} from "./types";

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function formatMoney(value: number | null, currency: NativeCurrency): string {
  if (!isFiniteNumber(value)) return "等待报价";
  return `${currencyPrefix(currency)}${value.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatQuantity(value: number): string {
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
}

function QuoteCell({
  quote,
  currency,
  freshness,
}: {
  quote: WorkbenchQuote | undefined;
  currency: NativeCurrency;
  freshness: QuoteFreshness;
}) {
  const price = quote?.price;
  const change = quote?.changePercent;
  const changeClass =
    !isFiniteNumber(change) || change === 0
      ? "text-muted-foreground"
      : change > 0
        ? "text-up"
        : "text-down";

  return (
    <div className="text-right">
      <div className="font-mono font-medium tabular-nums">
        {formatMoney(isFiniteNumber(price) ? price : null, currency)}
      </div>
      <div className={cn("mt-0.5 text-xs tabular-nums", changeClass)}>
        {isFiniteNumber(change)
          ? `${change >= 0 ? "+" : ""}${(change * 100).toFixed(2)}%`
          : "涨跌待更新"}
      </div>
      {freshness.isStale ? (
        <Badge
          variant="outline"
          className="mt-1 border-warn/40 bg-warn/10 text-warn"
        >
          {freshness.localDateLabel
            ? `截至 ${freshness.localDateLabel}`
            : "行情时间未知"}
        </Badge>
      ) : null}
    </div>
  );
}

export function WatchlistTable({
  items,
  groups,
  quotes,
  now,
  activeGroupId,
  onEdit,
  onRemove,
}: WatchlistTableProps) {
  const visibleItems = activeGroupId
    ? items.filter((item) => item.groupId === activeGroupId)
    : items;
  const groupById = new Map(groups.map((group) => [group.id, group]));
  const quoteBySymbol = new Map(
    quotes.map((quote) => [quote.symbol.trim().toUpperCase(), quote])
  );

  if (visibleItems.length === 0) {
    return (
      <EmptyState
        title={activeGroupId ? "该分组暂无标的" : "暂无自选标的"}
        description="添加标的后可维护仓位、价格提醒与交易逻辑。"
      />
    );
  }

  return (
    <Table className="min-w-[1180px] table-fixed">
      <TableHeader>
        <TableRow>
          <TableHead className="w-[190px] pl-4">标的 / 组</TableHead>
          <TableHead className="w-[150px] text-right">现价与涨跌</TableHead>
          <TableHead className="w-[170px] text-right">仓位</TableHead>
          <TableHead className="w-[190px] text-right">市值 / 浮盈亏</TableHead>
          <TableHead className="w-[180px]">提醒</TableHead>
          <TableHead>交易逻辑</TableHead>
          <TableHead className="w-[92px] pr-4 text-right">操作</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {visibleItems.map((item) => {
          const normalizedSymbol = item.symbol.trim().toUpperCase();
          const quote = quoteBySymbol.get(normalizedSymbol);
          const freshness = getQuoteFreshness(
            item.symbol,
            quote?.dataAsOf ?? null,
            now
          );
          const { currency } = inferInstrumentIdentity(item.symbol);
          const group = item.groupId ? groupById.get(item.groupId) : undefined;
          const quantity = isFiniteNumber(item.quantity) ? item.quantity : null;
          const averageCost = isFiniteNumber(item.averageCost)
            ? item.averageCost
            : null;
          const hasPosition =
            quantity !== null &&
            quantity > 0 &&
            averageCost !== null &&
            averageCost >= 0;
          const currentPrice =
            quote && isFiniteNumber(quote.price) && quote.price >= 0
              ? quote.price
              : null;
          const marketValue =
            hasPosition && quantity !== null && currentPrice !== null
              ? quantity * currentPrice
              : null;
          const unrealizedPnl =
            marketValue !== null &&
            hasPosition &&
            quantity !== null &&
            averageCost !== null
              ? marketValue - quantity * averageCost
              : null;
          const pnlClass =
            unrealizedPnl === null
              ? "text-muted-foreground"
              : unrealizedPnl >= 0
                ? "text-up"
                : "text-down";
          const alertAbove = isFiniteNumber(item.alertAbove)
            ? item.alertAbove
            : null;
          const alertBelow = isFiniteNumber(item.alertBelow)
            ? item.alertBelow
            : null;
          const aboveTriggered =
            !freshness.isStale &&
            currentPrice !== null &&
            alertAbove !== null &&
            currentPrice >= alertAbove;
          const belowTriggered =
            !freshness.isStale &&
            currentPrice !== null &&
            alertBelow !== null &&
            currentPrice <= alertBelow;

          return (
            <TableRow key={item.symbol}>
              <TableCell className="pl-4 whitespace-normal">
                <div className="truncate font-mono font-semibold">
                  {item.symbol}
                </div>
                <div className="mt-0.5 truncate text-xs text-muted-foreground">
                  {quote?.name || "名称待更新"}
                </div>
                {group && (
                  <Badge variant="secondary" className="mt-1.5 max-w-full">
                    <span className="truncate">{group.name}</span>
                  </Badge>
                )}
              </TableCell>
              <TableCell>
                <QuoteCell
                  quote={quote}
                  currency={currency}
                  freshness={freshness}
                />
              </TableCell>
              <TableCell className="text-right">
                {hasPosition ? (
                  <>
                    <div className="font-mono font-medium tabular-nums">
                      {`${formatQuantity(quantity ?? 0)} @ ${formatMoney(
                        averageCost,
                        currency
                      )}`}
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      数量 @ 平均成本
                    </div>
                  </>
                ) : (
                  <span className="text-xs text-muted-foreground">未建仓</span>
                )}
              </TableCell>
              <TableCell className="text-right">
                {hasPosition ? (
                  <>
                    <div className="font-mono font-medium tabular-nums">
                      {formatMoney(marketValue, currency)}
                    </div>
                    <div
                      className={cn(
                        "mt-0.5 font-mono text-xs tabular-nums",
                        pnlClass
                      )}
                    >
                      {formatMoney(unrealizedPnl, currency)}
                    </div>
                    {currentPrice !== null && freshness.isStale ? (
                      <div className="mt-0.5 text-[10px] text-warn">
                        旧价估算
                      </div>
                    ) : null}
                  </>
                ) : (
                  <span className="text-xs text-muted-foreground">未建仓</span>
                )}
              </TableCell>
              <TableCell className="whitespace-normal">
                {alertAbove !== null || alertBelow !== null ? (
                  <div className="space-y-1.5">
                    {alertAbove !== null && (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge
                          variant={aboveTriggered ? "outline" : "secondary"}
                          className={cn(
                            aboveTriggered &&
                              "border-warn/40 bg-warn/10 text-warn"
                          )}
                        >
                          {freshness.isStale
                            ? "旧价暂停"
                            : aboveTriggered
                              ? "已触发"
                              : "监控中"}
                        </Badge>
                        <span className="text-xs text-muted-foreground tabular-nums">
                          高于 {formatMoney(alertAbove, currency)}
                        </span>
                      </div>
                    )}
                    {alertBelow !== null && (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge
                          variant={belowTriggered ? "outline" : "secondary"}
                          className={cn(
                            belowTriggered &&
                              "border-warn/40 bg-warn/10 text-warn"
                          )}
                        >
                          {freshness.isStale
                            ? "旧价暂停"
                            : belowTriggered
                              ? "已触发"
                              : "监控中"}
                        </Badge>
                        <span className="text-xs text-muted-foreground tabular-nums">
                          低于 {formatMoney(alertBelow, currency)}
                        </span>
                      </div>
                    )}
                  </div>
                ) : (
                  <span className="text-xs text-muted-foreground">未设置</span>
                )}
              </TableCell>
              <TableCell className="whitespace-normal">
                {item.thesis ? (
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <span className="block max-w-[280px] cursor-help truncate text-xs text-foreground" />
                      }
                    >
                      {item.thesis}
                    </TooltipTrigger>
                    <TooltipContent className="max-w-sm whitespace-normal leading-5">
                      {item.thesis}
                    </TooltipContent>
                  </Tooltip>
                ) : (
                  <span className="text-xs text-muted-foreground">未记录</span>
                )}
              </TableCell>
              <TableCell className="pr-4 text-right">
                <div className="flex justify-end gap-1">
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`编辑 ${item.symbol}`}
                          onClick={() => onEdit(item)}
                        >
                          <PencilSimpleIcon />
                        </Button>
                      }
                    />
                    <TooltipContent>编辑自选</TooltipContent>
                  </Tooltip>
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`删除 ${item.symbol}`}
                          className="text-muted-foreground hover:text-destructive"
                          onClick={() => onRemove(item)}
                        >
                          <TrashIcon />
                        </Button>
                      }
                    />
                    <TooltipContent>删除自选</TooltipContent>
                  </Tooltip>
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
