"""量化引擎 CLI。

fetch：拉取日K（经 data-api /api/bars）与除权因子（TickFlow）到本地 Parquet 缓存。
run：运行策略回测。
screen：策略选股（取最新交易日截面，按 score 排序输出 Top N）。
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


def _cmd_list(_args: argparse.Namespace) -> int:
    """列出全部已加载策略。"""
    from app.runner import _default_strategy_dirs
    from app.strategy import StrategyRegistry
    reg = StrategyRegistry(_default_strategy_dirs())
    for s in reg.all():
        print(f"{s.strategy_id:24s} {s.name:12s} [{s.source}]  {s.meta.get('description','')}")
    for e in reg.load_errors():
        print(f"[加载失败] {e['file']}: {e['error']}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """运行策略回测（数据→矩阵→复权→策略→撮合→统计）。"""
    import json
    from app.runner import run_backtest
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("未指定有效 symbol")
        return 1
    end = _parse_date(args.end) if args.end else date.today()
    params = json.loads(args.params) if args.params else None
    out = run_backtest(symbols, args.strategy, _parse_date(args.start), end, params)
    st = out["stats"]
    print(f"策略 {out['strategy']} | {len(out['symbols'])} 只 | {out['range'][0]} ~ {out['range'][1]}")
    print(f"交易 {st['trades']} 笔 | 总收益 {st['total_return']:+.2%} | 年化 {st['annual_return']:+.2%} | "
          f"最大回撤 {st['max_drawdown']:.2%} | 夏普 {st['sharpe']:.2f} | 胜率 {st['win_rate']:.0%}")
    if out["unadjusted"]:
        print(f"[未复权降级] {len(out['unadjusted'])} 只：{','.join(out['unadjusted'][:5])}")
    return 0


def _cmd_screen(args: argparse.Namespace) -> int:
    """策略选股：最新交易日截面 entry=True 入选，按 score 排序输出。"""
    import json
    import math

    from app.runner import _default_strategy_dirs
    from app.screener import screen
    from app.strategy import StrategyRegistry

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("未指定有效 symbol")
        return 1
    end = _parse_date(args.end) if args.end else None
    params = json.loads(args.params) if args.params else None

    reg = StrategyRegistry(_default_strategy_dirs())
    try:
        strat = reg.get(args.strategy)
    except KeyError as e:
        print(f"策略不存在：{e}")
        return 1

    result = screen(args.strategy, symbols, end_date=end, params=params, registry=reg)
    # --limit 覆盖 META.limit（None 表示按 META 截断，0/负数表示不截断）
    rows = result.rows
    if args.limit is not None:
        rows = rows if args.limit <= 0 else rows[: args.limit]

    print(f"策略 {result.strategy_id}（{strat.name}）| 截面 {result.as_of} | "
          f"入选 {result.total} 只 | 标的池 {len(symbols)} 只")
    print(f"{'symbol':<14s} {'score':>10s} {'入场':^6s} {'出场':^6s} {'市场':<4s}")
    for r in rows:
        score = f"{r.score:.4f}" if not math.isnan(r.score) else "NaN"
        print(f"{r.symbol:<14s} {score:>10s} "
              f"{('是' if r.signals['entry'] else '否'):^6s} "
              f"{('是' if r.signals['exit'] else '否'):^6s} {r.market:<4s}")
    if result.unadjusted:
        print(f"[未复权降级] {len(result.unadjusted)} 只：{','.join(result.unadjusted[:5])}")
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

    p_list = sub.add_parser("list", help="列出全部策略")
    p_list.set_defaults(func=_cmd_list)

    p_run = sub.add_parser("run", help="运行策略回测")
    p_run.add_argument("strategy", help="策略 id（见 list）")
    p_run.add_argument("--symbols", required=True, help="逗号分隔的规范代码")
    p_run.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    p_run.add_argument("--end", default="", help="结束日期 YYYY-MM-DD（默认今天）")
    p_run.add_argument("--params", default="", help='策略参数 JSON，如 {"vol_ratio_min":1.5}')
    p_run.set_defaults(func=_cmd_run)

    p_screen = sub.add_parser("screen", help="策略选股（最新交易日截面）")
    p_screen.add_argument("strategy", help="策略 id（见 list）")
    p_screen.add_argument("--symbols", required=True, help="逗号分隔的规范代码")
    p_screen.add_argument("--end", default="", help="截面基准日 YYYY-MM-DD（默认今天）")
    p_screen.add_argument("--params", default="", help='策略参数 JSON，如 {"rsi_threshold":25}')
    p_screen.add_argument("--limit", type=int, default=None,
                          help="覆盖 META.limit；0/负数表示不截断")
    p_screen.set_defaults(func=_cmd_screen)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        # 无子命令时打印帮助
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
