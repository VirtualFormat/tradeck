"""量化引擎 CLI。

fetch：拉取日K（经 data-api /api/bars）与除权因子（TickFlow）到本地 Parquet 缓存。
run：运行策略回测（占位，见 plans/TASKS-QUANT-BACKTEST.md 阶段 B）。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date

from app.data import client, factors, store

_TODO_MSG = "未实现，见 plans/TASKS-QUANT-BACKTEST.md 阶段 A2/B"


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


async def _fetch_one(symbol: str, start: date, end: date) -> tuple[int, int]:
    """单标的增量拉取：算缓存缺口 → 只补缺口 → 合并落盘。返回 (缓存行数, 补拉行数)。"""
    cached = store.load(symbol)
    ranges = store.missing_ranges(cached, start, end)
    fetched = 0
    for r_start, r_end in ranges:
        bars = await client.fetch_bars([symbol], r_start, r_end)
        fetched += len(bars)
        cached = store.merge(cached, store.bars_to_frame(bars))
    if fetched:
        store.save(symbol, cached)
    return cached.height, fetched


def _cmd_fetch(args: argparse.Namespace) -> int:
    """拉取行情/因子数据到本地 Parquet 缓存。"""
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("未指定有效 symbol")
        return 1
    end = _parse_date(args.end) if args.end else date.today()
    start = _parse_date(args.start)

    async def _run() -> None:
        for symbol in symbols:
            cached_rows, fetched = await _fetch_one(symbol, start, end)
            print(f"{symbol}: 缓存 {cached_rows} 行（本次补拉 {fetched} 行）")
        if args.with_factors:
            got = await factors.fetch(symbols)
            print(f"除权因子：{len(got)}/{len(symbols)} 只有因子（其余无复权降级）")

    asyncio.run(_run())
    return 0


def _cmd_run(_args: argparse.Namespace) -> int:
    """运行策略回测（占位）。"""
    print(_TODO_MSG)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        prog="quant",
        description="tradeck 量化引擎 CLI",
    )
    sub = parser.add_subparsers(dest="command")

    p_fetch = sub.add_parser("fetch", help="拉取数据到本地缓存")
    p_fetch.add_argument("--symbols", required=True, help="逗号分隔的规范代码，如 AAPL,600519.SH")
    p_fetch.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    p_fetch.add_argument("--end", default="", help="结束日期 YYYY-MM-DD（默认今天）")
    p_fetch.add_argument("--with-factors", action="store_true", help="同时拉除权因子（需 TICKFLOW_API_KEY）")
    p_fetch.set_defaults(func=_cmd_fetch)

    p_run = sub.add_parser("run", help="运行回测（占位）")
    p_run.set_defaults(func=_cmd_run)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        # 无子命令时打印帮助
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
