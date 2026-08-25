"use client";

/**
 * 回测交易明细表：代码 / 买卖日期价 / 股数 / 持仓天数 / 盈亏 / 收益率 / 卖出原因
 * 超过 20 行简单分页（上一页 / 下一页）
 */
import { useState } from "react";
import { CaretLeftIcon, CaretRightIcon } from "@phosphor-icons/react";

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
  exitReasonLabel,
  fmtMoney,
  fmtNum,
  fmtPct,
  pnlStyle,
  type BacktestTrade,
} from "./types";

const PAGE_SIZE = 20;

export function TradesTable({ trades }: { trades: BacktestTrade[] }) {
  const [page, setPage] = useState(0);
  const pageCount = Math.ceil(trades.length / PAGE_SIZE);
  const safePage = Math.min(page, Math.max(pageCount - 1, 0));
  const rows = trades.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  return (
    <div className="space-y-3">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>代码</TableHead>
            <TableHead>买入日期</TableHead>
            <TableHead className="text-right">买入价</TableHead>
            <TableHead>卖出日期</TableHead>
            <TableHead className="text-right">卖出价</TableHead>
            <TableHead className="text-right">股数</TableHead>
            <TableHead className="text-right">持仓天数</TableHead>
            <TableHead className="text-right">盈亏</TableHead>
            <TableHead className="text-right">收益率</TableHead>
            <TableHead>卖出原因</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((trade, i) => (
            <TableRow
              key={`${trade.symbol}-${trade.entry_date}-${trade.exit_date}-${i}`}
            >
              <TableCell className="font-mono text-xs">
                {trade.symbol}
              </TableCell>
              <TableCell className="tabular-nums">
                {trade.entry_date ?? "—"}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {fmtNum(trade.entry_price)}
              </TableCell>
              <TableCell className="tabular-nums">
                {trade.exit_date ?? "—"}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {fmtNum(trade.exit_price)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {trade.shares == null ? "—" : trade.shares.toLocaleString("en-US")}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {trade.hold_days ?? "—"}
              </TableCell>
              <TableCell
                className="text-right tabular-nums"
                style={pnlStyle(trade.pnl)}
              >
                {fmtMoney(trade.pnl)}
              </TableCell>
              <TableCell
                className="text-right tabular-nums"
                style={pnlStyle(trade.ret)}
              >
                {fmtPct(trade.ret)}
              </TableCell>
              <TableCell>
                <Badge variant="outline">
                  {exitReasonLabel(trade.exit_reason)}
                </Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {pageCount > 1 && (
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.max(p - 1, 0))}
            disabled={safePage === 0}
          >
            <CaretLeftIcon />
            上一页
          </Button>
          <span className="text-xs text-muted-foreground tabular-nums">
            {safePage + 1} / {pageCount}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.min(p + 1, pageCount - 1))}
            disabled={safePage >= pageCount - 1}
          >
            下一页
            <CaretRightIcon />
          </Button>
        </div>
      )}
    </div>
  );
}
