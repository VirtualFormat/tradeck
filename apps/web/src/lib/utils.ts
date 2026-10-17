import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * 用户输入 → tradeck 标准 symbol：
 * - 6 位数字补 A 股后缀（60/68/9→.SH，00/30→.SZ，4/8→.BJ）
 * - ≤5 位数字港股补零（700 → 00700.HK）
 * - 已带后缀：港股补零；A 股旧写法 .SS → .SH（指数 000001.SS 除外）
 * - 其余（美股字母代码）原样大写返回
 */
export function normalizeSymbol(input: string): string {
  const s = input.trim().toUpperCase()
  if (!s) return s
  if (s.includes(".")) {
    const [code, suffix] = s.split(".")
    if (suffix === "HK" && /^\d{1,5}$/.test(code)) {
      return `${code.padStart(5, "0")}.HK`
    }
    if (suffix === "SS" && /^\d{6}$/.test(code) && code !== "000001") {
      return `${code}.SH`
    }
    return s
  }
  if (/^\d{6}$/.test(s)) {
    if (/^(60|68|9)/.test(s)) return `${s}.SH`
    if (/^(00|30)/.test(s)) return `${s}.SZ`
    if (/^(4|8)/.test(s)) return `${s}.BJ`
    return `${s}.SH`
  }
  if (/^\d{1,5}$/.test(s)) return `${s.padStart(5, "0")}.HK`
  return s
}
