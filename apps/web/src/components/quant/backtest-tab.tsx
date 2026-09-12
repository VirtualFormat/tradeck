"use client";

/**
 * Tab 1「策略回测」：左侧策略/参数/标的池(universe)/区间/资金/成本表单，右侧结果区
 * 结果区结构：概要条 → 核心指标卡网格（tooltip 解释）→ 选股/成交约束条 →
 * 净值曲线 → 收益分布 → 卖出归因 → 结果明细 Tabs（交易明细/按日期/选股分析）
 * 运行走任务化 API（POST run → 轮询 task，可取消）；任务接口缺失时一次性回退旧同步接口
 */
import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { CalendarIcon, PlayIcon, StopIcon } from "@phosphor-icons/react";

import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
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
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { EquityChart } from "./equity-chart";
import { MetricCard } from "./metric-card";
import { ReturnDistributionChart } from "./return-distribution-chart";
import { StrategyParamsForm, StrategyPicker } from "./strategy-picker";
import { TradesTable } from "./trades-table";
import {
  buildParamsPayload,
  EXIT_FILL_OPTIONS,
  exitReasonLabel,
  fmtMoney,
  fmtNum,
  fmtPct,
  parseSymbols,
  pnlStyle,
  selectionStatLabel,
  type BacktestResult,
  type BacktestRunResponse,
  type BacktestTaskProgress,
  type BacktestTaskState,
  type DailyTradeRow,
  type ParamValues,
  type PerSymbolStat,
  type SelectionStats,
  type StrategyDef,
} from "./types";

/** 任务轮询间隔（ms）与连续失败重试阈值（超过则提示连接中断 / 放弃） */
const POLL_INTERVAL_MS = 2000;
const POLL_RETRY_WARN = 3;
const POLL_RETRY_GIVEUP = 90;

/** 标的池 universe 选项（标的输入为空时生效，自定义标的时置灰） */
const UNIVERSE_OPTIONS = [
  { value: "tracked", label: "tracked 100 只（默认）" },
  { value: "cn", label: "A 股" },
  { value: "us", label: "美股" },
  { value: "hk", label: "港股" },
  { value: "all", label: "全部" },
] as const;
type UniverseValue = (typeof UNIVERSE_OPTIONS)[number]["value"];

/** 回测配置 localStorage 记忆（key 固定，页面加载时恢复、回测成功后写入） */
const BT_CONFIG_KEY = "quant-backtest-config";

interface BacktestSavedConfig {
  strategy?: string;
  symbols?: string;
  universe?: UniverseValue;
  start?: string;
  end?: string;
  capital?: string;
  commission?: string;
  stamp?: string;
  slippage?: string;
  minute_fill?: boolean;
  exit_fill?: string;
}

let savedConfigCache: BacktestSavedConfig | null | undefined;

/** 读一次 localStorage 并缓存（供各字段 useState lazy initializer 用，避免 effect 内 setState） */
function getSavedConfig(): BacktestSavedConfig | null {
  // SSR 预渲染时 window 不存在：直接返回 null 且不写缓存，
  // 避免服务端把 null 固化进缓存导致客户端 hydration 读不到记忆
  if (typeof window === "undefined") return null;
  if (savedConfigCache !== undefined) return savedConfigCache;
  try {
    const raw = window.localStorage.getItem(BT_CONFIG_KEY);
    savedConfigCache = raw ? (JSON.parse(raw) as BacktestSavedConfig) : null;
  } catch {
    savedConfigCache = null;
  }
  return savedConfigCache;
}

  /** 记忆恢复型 state：初始值优先取 localStorage，无记忆用默认值 */
function useSavedState<T>(
  pick: (saved: BacktestSavedConfig | null) => T | undefined,
  fallback: T
): [T, Dispatch<SetStateAction<T>>] {
  return useState<T>(() => pick(getSavedConfig()) ?? fallback);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 指标卡 label → tooltip 解释文案 */
const METRIC_HINTS: Record<string, string> = {
  总收益: "回测期末权益相对初始资金的累计收益率，已含费用/滑点/成交约束。",
  年化: "总收益按复利折算为一年，短周期可能被放大。",
  超额收益: "策略总收益减同期基准，正值跑赢基准。",
  最大回撤: "权益从历史高点到随后最低点的最大跌幅。",
  夏普: "平均收益÷总波动×√252 年化，越高单位波动收益越多。",
  索提诺: "平均收益÷下行偏差×√252，只惩罚负收益波动。",
  卡玛: "年化收益÷最大回撤绝对值。",
  胜率: "盈利交易占比，样本少时仅供参考。",
  盈亏比: "平均盈利÷平均亏损。",
  平均持仓: "已完成交易的平均持仓天数。",
  "回撤中位（蒙卡）": "蒙特卡洛重抽样后的最大回撤中位数，典型回撤水平。",
  "回撤 95%（蒙卡）": "蒙特卡洛重抽样后 95% 分位的最大回撤，极端回撤水平。",
};

interface BacktestTabProps {
  strategies: StrategyDef[];
  strategiesLoading: boolean;
  strategyId: string;
  onStrategyChange: (id: string) => void;
  paramValues: ParamValues;
  onParamValuesChange: (values: ParamValues) => void;
}

export function BacktestTab({
  strategies,
  strategiesLoading,
  strategyId,
  onStrategyChange,
  paramValues,
  onParamValuesChange,
}: BacktestTabProps) {
  const [symbolsInput, setSymbolsInput] = useSavedState(
    (s) => s?.symbols,
    ""
  );
  const [universe, setUniverse] = useSavedState<UniverseValue>(
    (s) =>
      s?.universe && UNIVERSE_OPTIONS.some((o) => o.value === s.universe)
        ? s.universe
        : undefined,
    "tracked"
  );
  const [startDate, setStartDate] = useSavedState((s) => s?.start, "");
  const [endDate, setEndDate] = useSavedState((s) => s?.end, "");
  const [initialCapital, setInitialCapital] = useSavedState(
    (s) => s?.capital,
    "100000"
  );
  const [commissionPct, setCommissionPct] = useSavedState(
    (s) => s?.commission,
    ""
  );
  const [stampTaxPct, setStampTaxPct] = useSavedState((s) => s?.stamp, "");
  const [slippageBps, setSlippageBps] = useSavedState(
    (s) => s?.slippage,
    ""
  );
  // 分钟口径（后端能力为阶段 H1，本组件为阶段 K3 展示）：信号成交日分钟K 优化成交价 + 卖出成交价口径
  const [minuteFill, setMinuteFill] = useSavedState(
    (s) => s?.minute_fill,
    false
  );
  const [exitFill, setExitFill] = useSavedState(
    (s) => s?.exit_fill,
    "open_t+1"
  );
  const [startOpen, setStartOpen] = useState(false);
  const [endOpen, setEndOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 任务化回测（阶段 K4）：轮询进度 / 停止标记 / 轮询连续失败（连接中断）状态
  const [taskProgress, setTaskProgress] =
    useState<BacktestTaskProgress | null>(null);
  const [stopping, setStopping] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [cancelTick, setCancelTick] = useState(0);
  const [taskActive, setTaskActive] = useState(false);
  const taskRef = useRef<{ id: string; cancelled: boolean } | null>(null);

  const strategy = strategies.find((s) => s.id === strategyId) ?? null;
  const symbols = parseSymbols(symbolsInput);
  const hasCustomSymbols = symbols.length > 0;

  // 策略 id 属父组件受控状态，挂载后从记忆恢复一次（父组件会校验并回退）。
  // 须等策略列表加载完再恢复：列表未到位时 onStrategyChange 会以 null 策略重置参数表单
  const strategyRestoredRef = useRef(false);
  useEffect(() => {
    if (strategyRestoredRef.current || strategies.length === 0) return;
    strategyRestoredRef.current = true;
    const savedStrategy = getSavedConfig()?.strategy;
    if (savedStrategy) onStrategyChange(savedStrategy);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategies.length]);

  // Date → YYYY-MM-DD（与 date-picker.tsx 同款格式化）
  function fmtDate(d: Date): string {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  async function runBacktest() {
    if (!strategyId || !startDate || loading) return;
    setLoading(true);
    setError(null);
    setTaskProgress(null);
    setReconnecting(false);
    setStopping(false);
    setTaskActive(false);
    const payload = {
      strategy_id: strategyId,
      // 留空 = 按 universe 选股池回测；自定义标的时 universe 不生效
      symbols: hasCustomSymbols ? symbols : null,
      universe: hasCustomSymbols ? undefined : universe,
      start: startDate,
      end: endDate || undefined,
      params: buildParamsPayload(strategy, paramValues),
      initial_capital: Number(initialCapital) || undefined,
      // 佣金按 % 输入，后端要小数（0.025% → 0.00025）
      commission_pct: commissionPct ? Number(commissionPct) / 100 : undefined,
      // 印花税同口径（% → 小数），滑点直接传 bps 数值
      stamp_tax_pct: stampTaxPct ? Number(stampTaxPct) / 100 : undefined,
      slippage_bps: slippageBps ? Number(slippageBps) : undefined,
      minute_fill: minuteFill,
      // 默认口径不传（与后端 MatcherConfig 缺省一致）
      exit_fill: exitFill === "open_t+1" ? undefined : exitFill,
    };
    try {
      const next = await runBacktestViaTask(payload);
      // 未停止才更新结果（停止保留上次结果）
      if (next !== null) setResult(next);
      // 回测成功后写入配置记忆
      try {
        window.localStorage.setItem(
          BT_CONFIG_KEY,
          JSON.stringify({
            strategy: strategyId,
            symbols: symbolsInput,
            universe,
            start: startDate,
            end: endDate,
            capital: initialCapital,
            commission: commissionPct,
            stamp: stampTaxPct,
            slippage: slippageBps,
            minute_fill: minuteFill,
            exit_fill: exitFill,
          } satisfies BacktestSavedConfig)
        );
      } catch {
        // localStorage 不可用时静默跳过
      }
    } catch {
      setError("回测请求失败，请检查网络后重试");
      setResult(null);
    } finally {
      setLoading(false);
      setTaskProgress(null);
      setReconnecting(false);
      setStopping(false);
      setTaskActive(false);
      taskRef.current = null;
    }
  }

  /**
   * 任务化回测：POST run 拿 task_id 后每 2s 轮询进度
   * run 接口 502（后端尚未上线任务 API）时一次性回退旧同步 POST /api/backtest
   * 返回 null 表示用户已停止（保留上次结果，不覆盖）
   */
  async function runBacktestViaTask(
    payload: Record<string, unknown>
  ): Promise<BacktestResult | null> {
    const runRes = await fetch("/api/quant/backtest/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!runRes.ok) {
      const legacy = await runBacktestLegacy(payload);
      if (!legacy) {
        setError("回测服务不可用，请稍后重试");
        setResult(null);
      }
      return legacy;
    }
    const { task_id } = (await runRes.json()) as BacktestRunResponse;
    taskRef.current = { id: task_id, cancelled: false };
    setTaskActive(true);
    let failures = 0;
    // 轮询直至终态；连续失败计数用于「连接中断」提示，超限后回退同步接口兜底
    while (true) {
      await sleep(POLL_INTERVAL_MS);
      const task = taskRef.current;
      if (!task || task.cancelled || task.id !== task_id) return null;
      let state: BacktestTaskState | null = null;
      try {
        const res = await fetch(`/api/quant/backtest/task/${task_id}`);
        if (res.ok) state = (await res.json()) as BacktestTaskState;
      } catch {
        state = null;
      }
      if (!state) {
        failures += 1;
        if (failures >= POLL_RETRY_WARN) setReconnecting(true);
        if (failures >= POLL_RETRY_GIVEUP) {
          setReconnecting(false);
          const legacy = await runBacktestLegacy(payload);
          if (!legacy) {
            setError("回测服务不可用，请稍后重试");
            setResult(null);
          }
          return legacy;
        }
        continue;
      }
      failures = 0;
      setReconnecting(false);
      if (state.progress) setTaskProgress(state.progress);
      if (state.status === "done") {
        if (!state.result) {
          setError("回测服务不可用，请稍后重试");
          setResult(null);
          return null;
        }
        return state.result;
      }
      if (state.status === "cancelled") return null;
      if (state.status === "failed") {
        setError(state.error ?? "回测执行失败");
        setResult(null);
        return null;
      }
    }
  }

  /** 旧同步接口一次性回退（任务 API 未部署时兜底），失败返回 null */
  async function runBacktestLegacy(
    payload: Record<string, unknown>
  ): Promise<BacktestResult | null> {
    try {
      const res = await fetch("/api/quant/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) return null;
      const body = (await res.json()) as BacktestResult & {
        error?: string;
      };
      // worker 失败时同步接口返回 200 + 错误骨架（{error, stats: null}），
      // 不能当成功结果渲染（P2-7）
      if (body.error || body.stats == null) return null;
      return body;
    } catch {
      return null;
    }
  }

  /** 停止回测：标记本地取消（停止轮询、保留上次结果），后端取消幂等可重试 */
  function stopBacktest() {
    const task = taskRef.current;
    if (!task) return;
    task.cancelled = true;
    setStopping(true);
    setCancelTick((t) => t + 1);
  }

  // 停止请求副作用：进入 stopping 态或之后每次重试点「停止」时发一次
  useEffect(() => {
    if (!stopping) return;
    const taskId = taskRef.current?.id;
    if (!taskId) return;
    let active = true;
    (async () => {
      try {
        const res = await fetch(`/api/quant/backtest/task/${taskId}/cancel`, {
          method: "POST",
        });
        if (!res.ok) throw new Error("cancel failed");
      } catch {
        if (active) setStopping(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [stopping, cancelTick]);

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">回测设置</CardTitle>
          <CardDescription>选择策略与参数，运行历史回测</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <StrategyPicker
            strategies={strategies}
            strategyId={strategyId}
            onStrategyChange={onStrategyChange}
            disabled={strategiesLoading || loading}
          />
          <StrategyParamsForm
            strategy={strategy}
            values={paramValues}
            onChange={onParamValuesChange}
            disabled={loading}
          />
          <div className="space-y-1.5">
            <Label htmlFor="quant-bt-symbols">标的（逗号分隔，可选）</Label>
            <Input
              id="quant-bt-symbols"
              placeholder="留空 = tracked 100 只（可逗号分隔自定义）"
              value={symbolsInput}
              onValueChange={(v) => setSymbolsInput(v)}
              disabled={loading}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="quant-bt-universe">选股池</Label>
            {hasCustomSymbols ? (
              <Tooltip>
                <TooltipTrigger
                  render={<span className="block cursor-not-allowed" />}
                >
                  <Select value={universe} disabled>
                    <SelectTrigger
                      id="quant-bt-universe"
                      className="w-full pointer-events-none"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {UNIVERSE_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TooltipTrigger>
                <TooltipContent>
                  自定义标的时 universe 不生效
                </TooltipContent>
              </Tooltip>
            ) : (
              <Select
                value={universe}
                onValueChange={(v: string | null) =>
                  setUniverse((v as UniverseValue) ?? "tracked")
                }
                disabled={loading}
              >
                <SelectTrigger id="quant-bt-universe" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {UNIVERSE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="quant-bt-start">开始日期</Label>
              <Popover open={startOpen} onOpenChange={setStartOpen}>
                <PopoverTrigger
                  render={
                    <Button
                      id="quant-bt-start"
                      variant="outline"
                      className="w-full justify-start gap-1.5 font-normal"
                      disabled={loading}
                    />
                  }
                >
                  <CalendarIcon className="size-3.5 text-fg-dim" />
                  {startDate || (
                    <span className="text-muted-foreground">选择日期</span>
                  )}
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <Calendar
                    mode="single"
                    selected={startDate ? new Date(`${startDate}T00:00:00`) : undefined}
                    onSelect={(d) => {
                      setStartDate(d ? fmtDate(d) : "");
                      setStartOpen(false);
                    }}
                    disabled={(date) => date > new Date()}
                  />
                </PopoverContent>
              </Popover>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="quant-bt-end">结束日期</Label>
              <Popover open={endOpen} onOpenChange={setEndOpen}>
                <PopoverTrigger
                  render={
                    <Button
                      id="quant-bt-end"
                      variant="outline"
                      className="w-full justify-start gap-1.5 font-normal"
                      disabled={loading}
                    />
                  }
                >
                  <CalendarIcon className="size-3.5 text-fg-dim" />
                  {endDate || (
                    <span className="text-muted-foreground">默认今天</span>
                  )}
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <Calendar
                    mode="single"
                    selected={endDate ? new Date(`${endDate}T00:00:00`) : undefined}
                    onSelect={(d) => {
                      setEndDate(d ? fmtDate(d) : "");
                      setEndOpen(false);
                    }}
                    disabled={(date) => date > new Date()}
                  />
                </PopoverContent>
              </Popover>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="quant-bt-capital">初始资金</Label>
              <Input
                id="quant-bt-capital"
                type="number"
                min={1}
                value={initialCapital}
                onValueChange={(v) => setInitialCapital(v)}
                disabled={loading}
              />
            </div>
            <div />
          </div>
          {/* 交易成本三项：留空 = 分市场默认（佣金/印花税 % 输入传小数，滑点传 bps） */}
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="quant-bt-commission">佣金（%）</Label>
              <Input
                id="quant-bt-commission"
                type="number"
                min={0}
                step={0.001}
                placeholder="如 0.025"
                value={commissionPct}
                onValueChange={(v) => setCommissionPct(v)}
                disabled={loading}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="quant-bt-stamp">印花税（%）</Label>
              <Input
                id="quant-bt-stamp"
                type="number"
                min={0}
                step={0.001}
                placeholder="如 0.05"
                value={stampTaxPct}
                onValueChange={(v) => setStampTaxPct(v)}
                disabled={loading}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="quant-bt-slippage">滑点（bps）</Label>
              <Input
                id="quant-bt-slippage"
                type="number"
                min={0}
                step={1}
                placeholder="如 5"
                value={slippageBps}
                onValueChange={(v) => setSlippageBps(v)}
                disabled={loading}
              />
            </div>
          </div>
          {/* 分钟口径设置（阶段 K3，对应 MatcherConfig.minute_fill / exit_fill） */}
          <Separator />
          <div className="space-y-2">
            <p className="text-xs font-medium text-fg-dim">成交口径（分钟）</p>
            <div className="flex items-center gap-2">
              <Checkbox
                id="quant-bt-minute-fill"
                checked={minuteFill}
                onCheckedChange={(checked) => setMinuteFill(checked === true)}
                disabled={loading}
              />
              <Label htmlFor="quant-bt-minute-fill" className="font-normal">
                分钟精确成交价（信号日分钟K 优化）
              </Label>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="quant-bt-exit-fill">卖出成交价口径</Label>
              <Select
                value={exitFill}
                onValueChange={(v: string | null) =>
                  setExitFill(v ?? "open_t+1")
                }
                disabled={loading}
              >
                <SelectTrigger id="quant-bt-exit-fill" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EXIT_FILL_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <Button
            className="w-full"
            onClick={runBacktest}
            disabled={loading || !strategyId || !startDate}
          >
            <PlayIcon />
            {loading ? "回测中…" : "运行回测"}
          </Button>
          {loading && (
            <Button
              className="w-full"
              variant="outline"
              onClick={stopBacktest}
              disabled={!taskActive}
            >
              <StopIcon />
              {stopping ? "停止中…" : "停止回测"}
            </Button>
          )}
        </CardContent>
      </Card>

      {loading ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">回测结果</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm text-muted-foreground tabular-nums">
                {reconnecting
                  ? "连接中断，重试中…"
                  : taskProgress
                    ? `回测中 · 第 ${taskProgress.day}/${taskProgress.total} 天${
                        taskProgress.date ? ` (${taskProgress.date})` : ""
                      }`
                    : "回测任务启动中…"}
              </p>
              {taskProgress && (
                <span className="text-xs text-muted-foreground tabular-nums">
                  {Math.min(
                    100,
                    Math.round(
                      (taskProgress.day / Math.max(taskProgress.total, 1)) * 100
                    )
                  )}
                  %
                </span>
              )}
            </div>
            <Progress
              value={
                taskProgress
                  ? Math.min(
                      100,
                      (taskProgress.day / Math.max(taskProgress.total, 1)) *
                        100
                    )
                  : null
              }
            />
            <BacktestResultSkeleton />
          </CardContent>
        </Card>
      ) : error ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">回测结果</CardTitle>
          </CardHeader>
          <CardContent>
            <EmptyState title={error} compact />
          </CardContent>
        </Card>
      ) : result ? (
        <BacktestResultView result={result} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">回测结果</CardTitle>
          </CardHeader>
          <CardContent>
            <EmptyState
              title="选择策略并运行回测"
              description="左侧配置策略、标的与区间后点击「运行回测」"
              compact
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/** 结果区骨架：概要条 + 指标卡网格 + 图表 + 表格占位 */
function BacktestResultSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-9 w-full" />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        {Array.from({ length: 12 }).map((_, i) => (
          <Skeleton key={i} className="h-20 w-full" />
        ))}
      </div>
      <Skeleton className="h-[320px] w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

function BacktestResultView({ result }: { result: BacktestResult }) {
  const { stats } = result;
  // 分钟频策略/错误骨架等异常结果无 stats（P1-2）：守卫降级为空态而非崩溃
  if (stats == null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">回测结果</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState
            title="该结果暂不支持展示"
            description="分钟频策略回放结果请使用同步回测路径查看，或结果不含统计数据"
            compact
          />
        </CardContent>
      </Card>
    );
  }
  const benchmark = result.benchmark ?? null;
  const unadjusted = result.unadjusted ?? stats.unadjusted ?? [];
  const trades = result.trades ?? [];
  const equityCurve = result.equity_curve ?? [];
  const exitStats = stats.exit_stats ?? {};
  const perSymbolStats = result.per_symbol_stats ?? [];
  const returnDist = result.return_distribution ?? [];
  const dailyRows = result.daily_trade_rows ?? [];
  const selectionStats = result.selection_stats ?? null;
  const hasExcess = benchmark?.excess_return != null;
  // 分钟成交覆盖统计（阶段 K3）：仅开了分钟口径（used+fallback>0）时标注
  const minuteUsed = result.minute_fill_used ?? 0;
  const minuteFallback = result.minute_fill_fallback ?? 0;
  const showMinuteCoverage = minuteUsed + minuteFallback > 0;

  const metrics: {
    label: string;
    value: string;
    colored?: number | null;
  }[] = [
    {
      label: "总收益",
      value: fmtPct(stats.total_return),
      colored: stats.total_return,
    },
    {
      label: "年化",
      value: fmtPct(stats.annual_return),
      colored: stats.annual_return,
    },
    ...(hasExcess
      ? [
          {
            label: "超额收益",
            value: fmtPct(benchmark?.excess_return),
            colored: benchmark?.excess_return,
          },
        ]
      : []),
    { label: "最大回撤", value: fmtPct(stats.max_drawdown) },
    { label: "夏普", value: fmtNum(stats.sharpe) },
    { label: "索提诺", value: fmtNum(stats.sortino) },
    { label: "卡玛", value: fmtNum(stats.calmar) },
    { label: "胜率", value: fmtPct(stats.win_rate) },
    { label: "盈亏比", value: fmtNum(stats.profit_loss_ratio) },
    {
      label: "交易数",
      value: stats.trades == null ? "—" : String(stats.trades),
    },
    { label: "平均持仓", value: `${fmtNum(stats.avg_hold_days, 1)} 天` },
    { label: "最终净值", value: fmtNum(stats.final_value) },
    ...(stats.mc_maxdd_p50 != null
      ? [{ label: "回撤中位（蒙卡）", value: fmtPct(stats.mc_maxdd_p50) }]
      : []),
    ...(stats.mc_maxdd_p95 != null
      ? [{ label: "回撤 95%（蒙卡）", value: fmtPct(stats.mc_maxdd_p95) }]
      : []),
  ];

  return (
    <div className="space-y-4">
      {/* 1. 概要条 */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 py-3">
          <Badge>{result.strategy}</Badge>
          <span className="text-xs text-muted-foreground tabular-nums">
            {result.range.join(" ~ ")}
            {stats.days != null && ` · ${stats.days} 天`}
          </span>
          {benchmark && (
            <Badge variant="outline">基准 {benchmark.symbol}</Badge>
          )}
          {unadjusted.length > 0 && (
            <Badge
              variant="outline"
              style={{
                color: "var(--warn)",
                borderColor:
                  "color-mix(in oklch, var(--warn) 50%, transparent)",
              }}
            >
              {unadjusted.length} 只未复权
            </Badge>
          )}
          {showMinuteCoverage && (
            <Badge
              variant="outline"
              style={{
                color: "var(--chart-1)",
                borderColor:
                  "color-mix(in oklch, var(--chart-1) 50%, transparent)",
              }}
            >
              分钟精确成交 {minuteUsed} 笔
              {minuteFallback > 0 && ` · 降级日K ${minuteFallback} 笔`}
            </Badge>
          )}
          {(result.elapsed_ms != null || result.run_id) && (
            <span className="text-[11px] text-muted-foreground/70 tabular-nums">
              {result.elapsed_ms != null &&
                `耗时 ${(result.elapsed_ms / 1000).toFixed(1)}s`}
              {result.elapsed_ms != null && result.run_id && " · "}
              {result.run_id && `run ${result.run_id}`}
            </span>
          )}
        </CardContent>
      </Card>

      {/* 2. 核心指标卡网格 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        {metrics.map((m) => (
          <MetricCard
            key={m.label}
            label={m.label}
            hint={METRIC_HINTS[m.label]}
            value={m.value}
            colored={m.colored}
          />
        ))}
      </div>

      {/* 3. 选股漏斗 / 成交约束统计条 */}
      {selectionStats && <SelectionStatsBar stats={selectionStats} />}

      {/* 4. 净值曲线 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">净值曲线</CardTitle>
          <CardDescription>归一化净值（起点 = 1）</CardDescription>
        </CardHeader>
        <CardContent>
          {equityCurve.length > 0 ? (
            <EquityChart data={equityCurve} />
          ) : (
            <EmptyState title="无净值曲线数据" compact className="h-[280px]" />
          )}
        </CardContent>
      </Card>

      {/* 5. 收益分布 */}
      {returnDist.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">收益分布</CardTitle>
            <CardDescription>按单笔收益率区间分桶的成交笔数</CardDescription>
          </CardHeader>
          <CardContent>
            <ReturnDistributionChart data={returnDist} />
          </CardContent>
        </Card>
      )}

      {/* 6. 卖出归因 */}
      {Object.keys(exitStats).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">卖出归因</CardTitle>
            <CardDescription>按卖出原因拆分的成交表现</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>卖出原因</TableHead>
                  <TableHead className="text-right">笔数</TableHead>
                  <TableHead className="text-right">胜率</TableHead>
                  <TableHead className="text-right">总盈亏</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(exitStats).map(([reason, s]) => (
                  <TableRow key={reason}>
                    <TableCell>
                      <Badge variant="outline">{exitReasonLabel(reason)}</Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {s.count}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtPct(s.win_rate)}
                    </TableCell>
                    <TableCell
                      className="text-right tabular-nums"
                      style={pnlStyle(s.total_pnl)}
                    >
                      {fmtMoney(s.total_pnl)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* 7. 结果明细 Tabs */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">结果明细</CardTitle>
          <CardDescription>共 {trades.length} 笔已完成交易</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="trades">
            <TabsList>
              <TabsTrigger value="trades">交易明细</TabsTrigger>
              <TabsTrigger value="daily">按日期</TabsTrigger>
              <TabsTrigger value="picks">选股分析</TabsTrigger>
            </TabsList>
            <TabsContent value="trades">
              {trades.length === 0 ? (
                <EmptyState
                  title="区间内无成交"
                  description="回测区间内策略未产生任何买卖信号"
                  compact
                />
              ) : (
                <TradesTable trades={trades} />
              )}
            </TabsContent>
            <TabsContent value="daily">
              {dailyRows.length === 0 ? (
                <EmptyState title="无按日成交数据" compact />
              ) : (
                <DailyTradeTable rows={dailyRows} />
              )}
            </TabsContent>
            <TabsContent value="picks">
              {perSymbolStats.length === 0 ? (
                <EmptyState title="无选股分析数据" compact />
              ) : (
                <PerSymbolStatsTable rows={perSymbolStats} />
              )}
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}

/** 选股漏斗 / 成交约束统计条（selection_stats 一行 Badge 展示） */
function SelectionStatsBar({ stats }: { stats: SelectionStats }) {
  const entries = Object.entries(stats).filter(
    ([, v]) => typeof v === "number"
  ) as [string, number][];
  if (entries.length === 0) return null;
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-2 py-3">
        <span className="text-xs text-muted-foreground">选股 / 成交约束</span>
        {entries.map(([key, value]) => (
          <Badge key={key} variant="outline">
            {selectionStatLabel(key)}{" "}
            <span className="tabular-nums">{value}</span>
          </Badge>
        ))}
      </CardContent>
    </Card>
  );
}

/** 按日成交聚合表（daily_trade_rows） */
function DailyTradeTable({ rows }: { rows: DailyTradeRow[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>日期</TableHead>
          <TableHead className="text-right">买入</TableHead>
          <TableHead className="text-right">卖出</TableHead>
          <TableHead className="text-right">当日盈亏</TableHead>
          <TableHead className="text-right">累计盈亏</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.date}>
            <TableCell className="tabular-nums">{r.date}</TableCell>
            <TableCell className="text-right tabular-nums">{r.buys}</TableCell>
            <TableCell className="text-right tabular-nums">{r.sells}</TableCell>
            <TableCell
              className="text-right tabular-nums"
              style={pnlStyle(r.realized_pnl)}
            >
              {fmtMoney(r.realized_pnl)}
            </TableCell>
            <TableCell
              className="text-right tabular-nums"
              style={pnlStyle(r.cumulative_pnl)}
            >
              {fmtMoney(r.cumulative_pnl)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** 按标的表现统计表（per_symbol_stats） */
function PerSymbolStatsTable({ rows }: { rows: PerSymbolStat[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>标的</TableHead>
          <TableHead className="text-right">次数</TableHead>
          <TableHead className="text-right">总收益</TableHead>
          <TableHead className="text-right">胜率</TableHead>
          <TableHead className="text-right">最佳</TableHead>
          <TableHead className="text-right">最差</TableHead>
          <TableHead className="text-right">总盈亏</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.symbol}>
            <TableCell>
              <span className="tabular-nums">{r.symbol}</span>
              {r.name && (
                <span className="ml-1.5 text-xs text-muted-foreground">
                  {r.name}
                </span>
              )}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {r.n_trades}
            </TableCell>
            <TableCell
              className="text-right tabular-nums"
              style={pnlStyle(r.total_return)}
            >
              {fmtPct(r.total_return)}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {fmtPct(r.win_rate)}
            </TableCell>
            <TableCell
              className="text-right tabular-nums"
              style={pnlStyle(r.best)}
            >
              {fmtPct(r.best)}
            </TableCell>
            <TableCell
              className="text-right tabular-nums"
              style={pnlStyle(r.worst)}
            >
              {fmtPct(r.worst)}
            </TableCell>
            <TableCell
              className="text-right tabular-nums"
              style={pnlStyle(r.total_pnl)}
            >
              {fmtMoney(r.total_pnl)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
