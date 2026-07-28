/**
 * 格式化工具
 */

import { format } from "date-fns";

export function fmtPrice(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function fmtChange(value: number | null | undefined): string {
  if (value == null) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function fmtPct(fraction: number | null | undefined): string {
  if (fraction == null) return "—";
  const sign = fraction > 0 ? "+" : "";
  return `${sign}${(fraction * 100).toFixed(2)}%`;
}

export function fmtVolume(volume: number | null | undefined): string {
  if (volume == null) return "—";
  if (volume >= 1e9) return `${(volume / 1e9).toFixed(2)}B`;
  if (volume >= 1e6) return `${(volume / 1e6).toFixed(2)}M`;
  if (volume >= 1e3) return `${(volume / 1e3).toFixed(2)}K`;
  return volume.toLocaleString("en-US");
}

/** 宏观指标百分比（无符号，用于绝对值如 CPI=3.30%） */
export function fmtMacroPct(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

/** 大额美元值（GDP 等） */
export function fmtBigUSD(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  return value.toLocaleString("en-US");
}

// ─── 数据时间标注（首页板块统一） ─────────────────────────

/** 日频数据：显日期 07-28（date 字符串 / 时间戳均可） */
export function fmtDataDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return format(d, "MM-dd");
}

/** 盘中分钟级数据：显时分 14:35（时间戳） */
export function fmtDataTime(value: string | null | undefined): string | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return format(d, "HH:mm");
}

/** 月度数据：显 2026年6月（与 /macro 页格式一致） */
export function fmtDataMonth(value: string | null | undefined): string | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return `${d.getFullYear()}年${d.getMonth() + 1}月`;
}
