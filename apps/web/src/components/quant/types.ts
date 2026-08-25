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
