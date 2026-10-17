"use client";

/**
 * Tab 4「因子挖掘」：候选库列表 + 发布（未达门槛的发布按钮禁用并展示原因）
 */
import { useCallback, useEffect, useState } from "react";
import { RocketLaunchIcon } from "@phosphor-icons/react";

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
import { Skeleton } from "@/components/ui/skeleton";
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

import { fmtPct, pnlStyle } from "./types";

interface MiningCandidate {
  candidate_id: string;
  combo: string;
  status: string;
  oos_sharpe: number | null;
  oos_max_drawdown: number | null;
  oos_trades: number | null;
  valid_folds: number | null;
  positive_fold_ratio: number | null;
  gate_reasons: string;
  created_at?: string | null;
  published_at?: string | null;
}

/** combo / gate_reasons 在后端存 JSON 字符串，解析失败时原样展示 */
function parseJsonText(raw: string | null | undefined): string {
  if (!raw) return "";
  try {
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.map(String).join(" + ");
    return String(parsed);
  } catch {
    return raw;
  }
}

function gateReasonList(raw: string | null | undefined): string[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map(String) : [String(parsed)];
  } catch {
    return raw ? [raw] : [];
  }
}

function statusBadge(status: string) {
  if (status === "published") {
    return <Badge variant="default">已发布</Badge>;
  }
  if (status === "rejected") {
    return <Badge variant="outline">已拒绝</Badge>;
  }
  return <Badge variant="secondary">待审核</Badge>;
}

export function MiningTab() {
  // candidates 为 null 表示加载中（初次或发布刷新），无需单独 loading 态
  const [candidates, setCandidates] = useState<MiningCandidate[] | null>(null);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch("/api/quant/mining", { cache: "no-store" });
        if (!cancelled) {
          setCandidates(
            res.ok ? ((await res.json()) as MiningCandidate[]) : []
          );
        }
      } catch {
        if (!cancelled) setCandidates([]);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  /** 发布操作后的列表刷新（事件回调场景，直接 setState） */
  const reload = useCallback(async () => {
    try {
      const res = await fetch("/api/quant/mining", { cache: "no-store" });
      setCandidates(res.ok ? ((await res.json()) as MiningCandidate[]) : []);
    } catch {
      setCandidates([]);
    }
  }, []);

  async function publish(candidateId: string) {
    if (publishingId) return;
    setPublishingId(candidateId);
    setNotice(null);
    try {
      const res = await fetch("/api/quant/mining/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate_id: candidateId }),
      });
      if (res.ok) {
        const data = (await res.json()) as {
          published: boolean;
          reason: string;
        };
        if (!data.published) setNotice(data.reason || "发布被拒绝");
      } else {
        setNotice("发布服务不可用，请稍后重试");
      }
    } catch {
      setNotice("发布请求失败，请检查网络后重试");
    } finally {
      setPublishingId(null);
      await reload();
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">候选库</CardTitle>
        <CardDescription>
          挖掘产出的因子组合候选，达到门槛后可发布为独立策略
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {notice && <EmptyState title={notice} compact inline />}
        {candidates === null ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : !candidates || candidates.length === 0 ? (
          <EmptyState
            title="暂无候选，先运行挖掘"
            description="因子挖掘任务产出的候选会显示在这里"
            compact
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>因子组合</TableHead>
                <TableHead className="text-right">OOS 夏普</TableHead>
                <TableHead className="text-right">OOS 最大回撤</TableHead>
                <TableHead className="text-right">正收益折占比</TableHead>
                <TableHead className="text-right">有效折数</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {candidates.map((c) => {
                const reasons = gateReasonList(c.gate_reasons);
                const canPublish = c.status === "pending";
                const blocked = reasons.length > 0;
                return (
                  <TableRow key={c.candidate_id}>
                    <TableCell className="max-w-[280px]">
                      <span className="block truncate font-mono text-xs">
                        {parseJsonText(c.combo) || c.candidate_id}
                      </span>
                    </TableCell>
                    <TableCell
                      className="text-right tabular-nums"
                      style={pnlStyle(c.oos_sharpe)}
                    >
                      {c.oos_sharpe == null ? "—" : c.oos_sharpe.toFixed(2)}
                    </TableCell>
                    <TableCell
                      className="text-right tabular-nums"
                      style={pnlStyle(c.oos_max_drawdown)}
                    >
                      {fmtPct(c.oos_max_drawdown)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtPct(c.positive_fold_ratio)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {c.valid_folds ?? "—"}
                    </TableCell>
                    <TableCell>{statusBadge(c.status)}</TableCell>
                    <TableCell>
                      {canPublish &&
                        (blocked ? (
                          <Tooltip>
                            <TooltipTrigger
                              render={<span className="inline-flex" />}
                            >
                              <Button size="sm" variant="outline" disabled>
                                <RocketLaunchIcon />
                                发布
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>
                              未达门槛：{reasons.join("；")}
                            </TooltipContent>
                          </Tooltip>
                        ) : (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={publishingId === c.candidate_id}
                            onClick={() => publish(c.candidate_id)}
                          >
                            <RocketLaunchIcon />
                            {publishingId === c.candidate_id
                              ? "发布中…"
                              : "发布"}
                          </Button>
                        ))}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
