"use client";

/**
 * 分钟频策略回放结果展示（阶段 L）：
 * 概要条（策略/区间/回放天数/涨停拒买/未复权/耗时）→ 命中明细表
 * skipped_days 有值时折叠展开全部日期（复用 walkforward-tab 的 skipped 模式）
 */
import { CaretDownIcon } from "@phosphor-icons/react";

import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import {
  fmtNum,
  type MinuteReplayHit,
  type MinuteReplayResult,
} from "./types";

/** 命中按交易日 + 触发时刻排序（字符串 ISO 日期 / "HH:MM" 均可字典序比较） */
function sortHits(hits: MinuteReplayHit[]): MinuteReplayHit[] {
  return [...hits].sort(
    (a, b) =>
      a.trade_date.localeCompare(b.trade_date) ||
      a.trigger_time.localeCompare(b.trigger_time)
  );
}

export function MinuteReplayView({ result }: { result: MinuteReplayResult }) {
  const [start, end] = result.range;
  const hits = sortHits(result.hits ?? []);
  const skippedDays = result.skipped_days ?? [];
  const unadjusted = result.unadjusted ?? [];

  return (
    <div className="space-y-4">
      {/* 概要条 */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 py-3">
          <Badge>{result.strategy}</Badge>
          <Badge variant="secondary" className="tabular-nums">
            {start ?? "—"} ~ {end ?? "—"}
          </Badge>
          <Badge variant="outline" className="tabular-nums">
            回放 {result.replayed_days} 天
            {skippedDays.length > 0 ? `，跳过 ${skippedDays.length} 天` : ""}
          </Badge>
          {result.buy_limit_up > 0 && (
            <Badge variant="outline" className="tabular-nums">
              涨停拒买 {result.buy_limit_up} 次
            </Badge>
          )}
          {unadjusted.length > 0 && (
            <Badge variant="outline" className="tabular-nums">
              未复权 {unadjusted.length} 只
            </Badge>
          )}
          {result.elapsed_ms != null && (
            <span className="text-[11px] text-muted-foreground/70 tabular-nums">
              耗时 {(result.elapsed_ms / 1000).toFixed(1)}s
            </span>
          )}
        </CardContent>
      </Card>

      {/* 折叠跳过日明细（跳过不可见会让用户误判为 bug） */}
      {skippedDays.length > 0 && (
        <Card>
          <CardContent className="py-3">
            <Collapsible>
              <CollapsibleTrigger
                render={
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full justify-start gap-1.5 text-xs text-muted-foreground"
                  />
                }
              >
                <CaretDownIcon />
                跳过 {skippedDays.length} 天（无分钟分区或单日执行失败，展开查看日期）
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {skippedDays.map((d) => (
                    <Badge key={d} variant="outline" className="tabular-nums">
                      {d}
                    </Badge>
                  ))}
                </div>
              </CollapsibleContent>
            </Collapsible>
          </CardContent>
        </Card>
      )}

      {/* 命中明细 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">命中明细</CardTitle>
          <CardDescription>
            盘中触发分钟级买入信号的记录，共 {hits.length} 条
          </CardDescription>
        </CardHeader>
        <CardContent>
          {hits.length === 0 ? (
            <EmptyState
              title="区间内无触发"
              description="回放区间内策略未触发任何盘中买入信号"
              compact
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>日期</TableHead>
                  <TableHead>标的</TableHead>
                  <TableHead className="text-right">成交价</TableHead>
                  <TableHead>触发时刻</TableHead>
                  <TableHead className="text-right">评分</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {hits.map((h, i) => (
                  <TableRow
                    key={`${h.trade_date}-${h.symbol}-${h.trigger_time}-${i}`}
                  >
                    <TableCell className="tabular-nums">
                      {h.trade_date}
                    </TableCell>
                    <TableCell className="tabular-nums">{h.symbol}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {h.entry_price != null ? fmtNum(h.entry_price, 3) : "—"}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {h.trigger_time}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {h.score != null ? fmtNum(h.score, 2) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
