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
  unadjusted?: string[];
  trades?: BacktestTrade[];
  equity_curve?: EquityPoint[];
  benchmark?: BacktestBenchmark | null;
  /** 分钟成交覆盖统计（阶段 H1）：走分钟口径笔数 / 分钟数据缺失降级日K 笔数 */
  minute_fill_used?: number | null;
  minute_fill_fallback?: number | null;
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
