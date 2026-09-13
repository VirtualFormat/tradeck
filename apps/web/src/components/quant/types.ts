/**
 * 量化工作台共享类型与工具函数
 * 契约以 quant 后端（apps/quant/app/api.py）为准，前端只经 Next 代理路由消费
 */

export interface StrategyParam {
  id: string;
  label?: string;
  type?: string;
  default?: unknown;
  min?: number;
  max?: number;
  step?: number;
  options?: (string | number)[];
}

export interface StrategyDef {
  id: string;
  name: string;
  description: string;
  tags: string[];
  source: string;
  params: StrategyParam[];
  stop_loss?: number | null;
  max_hold_days?: number | null;
  /** META 只读定义（策略定义速览面板展示）：scoring 权重 / order_by / limit */
  scoring?: Record<string, number> | null;
  order_by?: string | null;
  limit?: number | null;
}

/** 参数表单值统一用字符串承载（bool 用 "true"/"false"），提交前再转回原生类型 */
export type ParamValues = Record<string, string>;

export function defaultParamValues(strategy: StrategyDef | null): ParamValues {
  const values: ParamValues = {};
  for (const p of strategy?.params ?? []) {
    values[p.id] = p.default == null ? "" : String(p.default);
  }
  return values;
}

/** 提交参数：按 schema 类型把字符串还原成 number / boolean，空值忽略 */
export function buildParamsPayload(
  strategy: StrategyDef | null,
  values: ParamValues
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const p of strategy?.params ?? []) {
    const raw = values[p.id];
    if (raw == null || raw === "") continue;
    if (p.type === "bool") {
      payload[p.id] = raw === "true";
    } else if (p.type === "int") {
      const n = Number.parseInt(raw, 10);
      if (!Number.isNaN(n)) payload[p.id] = n;
    } else if (p.type === "select") {
      payload[p.id] = raw;
    } else {
      const n = Number(raw);
      if (!Number.isNaN(n)) payload[p.id] = n;
    }
  }
  return payload;
}

/** 逗号 / 空白分隔的标的输入 → symbol 数组 */
export function parseSymbols(input: string): string[] {
  return input
    .split(/[\s,，]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** 收益类数值着色：正 var(--up) 红，负 var(--down) 绿 */
export function pnlStyle(
  value: number | null | undefined
): React.CSSProperties {
  if (value == null || value === 0) return {};
  return { color: value > 0 ? "var(--up)" : "var(--down)" };
}

export function fmtPct(fraction: number | null | undefined): string {
  if (fraction == null) return "—";
  const sign = fraction > 0 ? "+" : "";
  return `${sign}${(fraction * 100).toFixed(2)}%`;
}

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value == null) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** 盈亏类金额格式化（正数带 + 号，负号由数字自带） */
export function fmtMoney(value: number | null | undefined, digits = 2): string {
  if (value == null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${fmtNum(value, digits)}`;
}

/* ---------- 回测结果契约（POST /api/quant/backtest） ---------- */

export interface ExitStat {
  count: number;
  win_rate: number | null;
  total_pnl: number | null;
  avg_pnl: number | null;
}

export interface BacktestStats {
  total_return: number | null;
  annual_return: number | null;
  max_drawdown: number | null;
  annual_volatility: number | null;
  sharpe: number | null;
  sortino: number | null;
  calmar: number | null;
  trades: number | null;
  win_rate: number | null;
  profit_loss_ratio: number | null;
  turnover: number | null;
  avg_hold_days: number | null;
  days: number | null;
  final_value: number | null;
  exit_stats?: Record<string, ExitStat> | null;
  unadjusted?: string[];
  risk_free_rate?: number | null;
  /** 蒙特卡洛回撤分布（阶段 K4）：中位 / 95% 分位最大回撤，null 表示未模拟 */
  mc_maxdd_p50?: number | null;
  mc_maxdd_p95?: number | null;
}

export interface BacktestTrade {
  symbol: string;
  entry_date: string | null;
  exit_date: string | null;
  entry_price: number | null;
  exit_price: number | null;
  shares: number | null;
  pnl: number | null;
  ret: number | null;
  hold_days: number | null;
  exit_reason: string | null;
  /** 标的名称与开仓仓位占比（阶段 M，可选，后端缺省不展示） */
  name?: string | null;
  position_pct?: number | null;
  /** 成交口径标注（阶段 H1 分钟口径）：daily / minute_ref / minute_vwap /
   *  minute_close / minute_trigger；旧响应缺省视为 daily */
  entry_fill_mode?: string | null;
  exit_fill_mode?: string | null;
}

export interface EquityPoint {
  date: string;
  /** 策略归一化净值（起点 = 1） */
  value: number | null;
  /** 基准归一化净值（起点 = 1），无基准时为 null */
  benchmark: number | null;
}

export interface BacktestBenchmark {
  symbol: string;
  market: string | null;
  total_return: number | null;
  excess_return: number | null;
}

export interface BacktestResult {
  stats: BacktestStats;
  strategy: string;
  symbols: string[];
  range: string[];
  /** 任务化回测（阶段 K4）：任务 id 与耗时，旧响应缺省不展示 */
  run_id?: string | null;
  elapsed_ms?: number | null;
  unadjusted?: string[];
  trades?: BacktestTrade[];
  equity_curve?: EquityPoint[];
  benchmark?: BacktestBenchmark | null;
  /** 分钟成交覆盖统计（阶段 H1）：走分钟口径笔数 / 分钟数据缺失降级日K 笔数 */
  minute_fill_used?: number | null;
  minute_fill_fallback?: number | null;
  /** 按标的拆分的表现统计（选股分析 Tab） */
  per_symbol_stats?: PerSymbolStat[];
  /** 单笔收益分布直方图分桶（收益分布图） */
  return_distribution?: ReturnDistBucket[];
  /** 按日成交聚合（按日期 Tab） */
  daily_trade_rows?: DailyTradeRow[];
  /** 选股漏斗 / 成交约束统计，null 表示后端未提供 */
  selection_stats?: SelectionStats | null;
  /** 执行层拦截 / 跳过计数（阶段 M，有值才渲染成交约束条） */
  execution_stats?: ExecutionStats | null;
  /** 因子归因（阶段 N3）：对比盈利单与亏损单入场信号日的因子均值，
   * null / undefined 表示后端未提供（旧响应缺省不展示「因子归因」Tab） */
  factor_attribution?: FactorAttribution | null;
}

/** 因子归因契约（BacktestResult.factor_attribution，阶段 N3） */
export interface FactorAttribution {
  factors: FactorAttributionRow[];
  n_win: number;
  n_lose: number;
  /** 入场信号日无有效因子数据而跳过的笔数（有值才提示） */
  skipped_no_signal_day?: number;
  /** 信号日定位口径：prev_day = 成交日前一交易日（open_t+1）；
   *  same_day = 成交日当天（close_t 研究口径） */
  signal_day_assumption?: "prev_day" | "same_day";
}

export interface FactorAttributionRow {
  /** enriched 指标英文名（如 ma5 / rsi14） */
  factor: string;
  win_mean: number | null;
  lose_mean: number | null;
  diff: number | null;
}

/** enriched 指标英文名 → 中文标签（未知 key 原样展示，见 quant 端 matrix/enriched.py） */
export const FACTOR_LABELS: Record<string, string> = {
  ma5: "MA5",
  ma10: "MA10",
  ma20: "MA20",
  ma60: "MA60",
  ema12: "EMA12",
  ema26: "EMA26",
  macd_dif: "MACD DIF",
  macd_dea: "MACD DEA",
  macd_hist: "MACD HIST",
  rsi14: "RSI14",
  boll_upper: "BOLL 上轨",
  boll_lower: "BOLL 下轨",
  momentum_5d: "动量5日",
  momentum_20d: "动量20日",
  vol_ratio_5d: "量比",
  high_20d: "20 日高点",
  low_20d: "20 日低点",
};

export function factorLabel(factor: string): string {
  return FACTOR_LABELS[factor] ?? factor;
}

/** 单标的表现统计（per_symbol_stats） */
export interface PerSymbolStat {
  symbol: string;
  name?: string | null;
  n_trades: number;
  total_return: number | null;
  win_rate: number | null;
  /** 最佳 / 最差单笔收益率（小数） */
  best: number | null;
  worst: number | null;
  total_pnl: number | null;
}

/** 收益分布直方图分桶（return_distribution，bucket 为小数区间） */
export interface ReturnDistBucket {
  bucket_start: number;
  bucket_end: number;
  /** 后端预格式化区间文案（如 "+2~+4%"） */
  range?: string;
  count: number;
  /** 占比（0~1） */
  ratio?: number;
}

/** 按日成交聚合行（daily_trade_rows） */
export interface DailyTradeRow {
  date: string;
  buys: number;
  sells: number;
  realized_pnl: number | null;
  cumulative_pnl: number | null; // 后端键名 cumulative_pnl（累计已实现盈亏）
}

/** 选股漏斗 / 成交约束统计（selection_stats，均为整数计数）。
 * 阶段 M：扩展执行层拦截计数（涨停拦截 / 满仓跳过 / 现金不足 / 冷却跳过等） */
export interface SelectionStats {
  signals_entry?: number | null;
  signals_exit?: number | null;
  filled_trades?: number | null;
  [key: string]: number | null | undefined;
}

/** selection_stats 字段 → 中文文案（未知 key 原样展示） */
export const SELECTION_STAT_LABELS: Record<string, string> = {
  signals_entry: "买入信号",
  signals_exit: "卖出信号",
  filled_trades: "实际成交",
  blocked_buy_limit: "涨停拦截买入",
  blocked_sell_limit: "跌停拦截卖出",
  skipped_max_positions: "满仓跳过",
  skipped_no_cash: "现金不足",
  skipped_cooldown: "冷却跳过",
};

export function selectionStatLabel(key: string): string {
  return SELECTION_STAT_LABELS[key] ?? key;
}

/** 执行层拦截 / 跳过计数键（selection_stats 内独立分组渲染，文案同 SELECTION_STAT_LABELS） */
export const EXECUTION_STAT_KEYS = [
  "blocked_buy_limit",
  "blocked_sell_limit",
  "skipped_max_positions",
  "skipped_no_cash",
  "skipped_cooldown",
] as const;

export function isExecutionStatKey(key: string): boolean {
  return (EXECUTION_STAT_KEYS as readonly string[]).includes(key);
}

/** 成交约束计数（result.execution_stats，Record<string, number> 扩展宽松键） */
export type ExecutionStats = Record<string, number>;

/* ---------- 任务化回测契约（阶段 K4） ---------- */

/** POST /api/quant/backtest/run 响应 */
export interface BacktestRunResponse {
  task_id: string;
}

export type BacktestTaskStatus =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "cancelled";

export interface BacktestTaskProgress {
  day: number;
  total: number;
  date?: string | null;
}

/** GET /api/quant/backtest/task/{id} 响应 */
export interface BacktestTaskState {
  status: BacktestTaskStatus;
  progress?: BacktestTaskProgress | null;
  result?: BacktestResult | null;
  error?: string | null;
}

/** 卖出原因英文 key → 中文文案 */
export const EXIT_REASON_LABELS: Record<string, string> = {
  signal: "信号卖出",
  stop_loss: "止损",
  take_profit: "止盈",
  max_hold: "到期",
  end: "期末强平",
};

export function exitReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "—";
  return EXIT_REASON_LABELS[reason] ?? reason;
}

/* ---------- 分钟成交口径（阶段 H1/H3） ---------- */

/** 卖出成交价口径请求值 → 中文标签（BacktestRequest.exit_fill） */
export const EXIT_FILL_OPTIONS: { value: string; label: string }[] = [
  { value: "open_t+1", label: "次日开盘（默认）" },
  { value: "close_t", label: "当日收盘" },
  { value: "signal_next_minute", label: "盘中触发（分钟确认）" },
];

/** 逐笔成交口径标注 → 中文标签 */
export const FILL_MODE_LABELS: Record<string, string> = {
  daily: "日K",
  minute_ref: "穿越价",
  minute_vwap: "VWAP",
  minute_close: "分钟收盘",
  minute_trigger: "盘中触发",
};

export function fillModeLabel(mode: string | null | undefined): string {
  if (!mode) return FILL_MODE_LABELS.daily;
  return FILL_MODE_LABELS[mode] ?? mode;
}

/** 是否为分钟口径（非 daily 标注），用于 Badge 高亮区分 */
export function isMinuteFillMode(mode: string | null | undefined): boolean {
  return !!mode && mode !== "daily";
}

/* ---------- 参数优化契约（POST /api/quant/optimize，阶段 M3） ---------- */

/** 优化目标请求值（BacktestStats 同名键 → 后端直接取统计字段） */
export const OBJECTIVE_OPTIONS: { value: string; label: string }[] = [
  { value: "total_return", label: "总收益" },
  { value: "annual_return", label: "年化" },
  { value: "sharpe", label: "夏普" },
  { value: "sortino", label: "索提诺" },
  { value: "calmar", label: "卡玛" },
  { value: "win_rate", label: "胜率" },
  { value: "profit_loss_ratio", label: "盈亏比" },
  { value: "max_drawdown", label: "最大回撤" },
];

export function objectiveLabel(objective: string): string {
  return (
    OBJECTIVE_OPTIONS.find((o) => o.value === objective)?.label ?? objective
  );
}

/** 单个参数网格：min/max/step 区间，或显式值数组 */
export type ParamGridRange = { min?: number; max?: number; step?: number };

/** 优化结果行（results 数组，附带回测统计的宽松键） */
export interface OptimizeResultRow {
  params: Record<string, unknown>;
  objective_raw: number | null;
  rank: number;
  total_return?: number | null;
  sharpe?: number | null;
  max_drawdown?: number | null;
  trades?: number | null;
  [key: string]: unknown;
}

export interface OptimizeResult {
  best_params: Record<string, unknown> | null;
  best_score: number | null;
  n_combinations: number;
  n_completed: number;
  n_errors: number;
  results: OptimizeResultRow[];
  elapsed_ms: number | null;
}

/** 排名表最多展示行数 */
export const OPTIMIZE_TABLE_MAX_ROWS = 50;

/* ---------- 步进优化契约（POST /api/quant/walkforward，阶段 M3） ---------- */

/** 每折明细（train/test 区间 + 该折最优参数 + 样本外指标，宽松键向后兼容） */
export interface WalkforwardFold {
  train_start?: string | null;
  train_end?: string | null;
  test_start?: string | null;
  test_end?: string | null;
  best_params?: Record<string, unknown> | null;
  oos_total_return?: number | null;
  oos_sharpe?: number | null;
  /** 该折 OOS 是否较 IS 退化（true=过拟合信号） */
  oos_degraded?: boolean | null;
  [key: string]: unknown;
}

/** 折明细的样本外收益 / 夏普取值（后端扁平键 oos_total_return/oos_sharpe，
 * 阶段 M review P0-2 收敛为单一形态，不做臆测回退） */
export function foldOosReturn(fold: WalkforwardFold): number | null {
  return fold.oos_total_return ?? null;
}

export function foldOosSharpe(fold: WalkforwardFold): number | null {
  return fold.oos_sharpe ?? null;
}

export function foldParams(fold: WalkforwardFold): Record<string, unknown> {
  return fold.best_params ?? {};
}

export interface WalkforwardResult {
  compounded_oos_return: number | null;
  n_folds: number;
  n_planned_folds: number;
  /** 折叠失败跳过的折（含原因） */
  n_skipped?: number;
  skipped?: { index?: number; reason?: string; [key: string]: unknown }[];
  /** IS→OOS 退化（正值 = 样本外退化/过拟合信号） */
  degradation?: number | null;
  /** OOS 总收益 > 0 的折占比 */
  consistency?: number | null;
  folds: WalkforwardFold[];
  elapsed_ms?: number | null;
}
