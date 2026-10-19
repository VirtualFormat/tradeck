"""结果裁剪单测：大体量假结果下 summary ≤10KB、净值降采样保留首尾、最好/最差各 10、分页。"""

from __future__ import annotations

import unittest

from app.results import (
    SUMMARY_MAX_BYTES,
    downsample,
    dumps,
    paginate,
    section_items,
    summarize,
)


def big_position_result(
    n_days: int = 2500,
    n_trades: int = 8000,
    n_symbols: int = 500,
    long_name: str = "超长中文证券简称" * 10,
) -> dict:
    """与 runner.run_backtest 返回结构同构的大体量假结果（字段名照抄 runner.py）。

    long_name 默认取极端长度（压测摘要的逐级收缩）；契约字段测试传真实长度的简称。
    """
    symbols = [f"{600000 + i:06d}.SH" for i in range(n_symbols)]
    equity_curve = [
        {
            "date": f"2015-01-{i:05d}",
            "value": 1.0 + i * 0.000123456789,
            "benchmark": 1.0 + i * 0.0000987654321,
        }
        for i in range(n_days)
    ]
    trades = [
        {
            "symbol": symbols[i % n_symbols],
            "name": long_name,
            "entry_date": "2020-01-02",
            "exit_date": "2020-02-03",
            "entry_price": 10.123456,
            "exit_price": 11.654321,
            "shares": 1000,
            "pnl": 1530.864,
            "ret": 0.151234,
            "hold_days": 32,
            "exit_reason": "signal",
            "entry_fill_mode": "daily",
            "exit_fill_mode": "daily",
            "position_pct": None,
        }
        for i in range(n_trades)
    ]
    per_symbol = sorted(
        (
            {
                "symbol": s,
                "name": long_name,
                "n_trades": 16,
                "total_return": round((i - n_symbols / 2) / n_symbols, 4),
                "win_rate": 0.5625,
                "best": 0.31,
                "worst": -0.12,
                "total_pnl": 12345.67,
            }
            for i, s in enumerate(symbols)
        ),
        key=lambda r: r["total_return"],
        reverse=True,
    )
    exit_stats = {
        reason: {"count": 100, "win_rate": 0.5, "total_pnl": 1234.5, "avg_pnl": 12.345}
        for reason in (
            "signal",
            "stop_loss",
            "take_profit",
            "trailing_stop",
            "max_hold_days",
            "end_of_test",
        )
    }
    return {
        "run_id": "f" * 32,
        "elapsed_ms": 123456.7,
        "stats": {
            "total_return": 0.523456789,
            "annual_return": 0.0812345,
            "max_drawdown": -0.2345678,
            "annual_volatility": 0.21,
            "sharpe": 1.2345,
            "sortino": 1.5,
            "calmar": 0.35,
            "trades": n_trades,
            "win_rate": 0.55,
            "profit_loss_ratio": 1.8,
            "turnover": 12.3,
            "avg_hold_days": 21.5,
            "exit_stats": exit_stats,
            "mc_maxdd_p50": -0.2,
            "mc_maxdd_p95": -0.35,
            "days": n_days,
            "final_value": 1523456.78,
            "unadjusted": symbols,
            "risk_free_rate": 0.0,
        },
        "strategy": "ma_golden_cross",
        "symbols": symbols,
        "range": ["2015-01-05", "2025-12-31"],
        "unadjusted": symbols,
        "trades": trades,
        "equity_curve": equity_curve,
        "benchmark": {
            "symbol": "000300.SH",
            "market": "CN",
            "total_return": 0.3,
            "excess_return": 0.22,
        },
        "minute_fill_used": 0,
        "minute_fill_fallback": 0,
        "execution_stats": {"blocked_buy_limit": 12, "skipped_max_positions": 3456},
        "per_symbol_stats": per_symbol,
        "return_distribution": [
            {
                "bucket_start": -0.2,
                "bucket_end": -0.18,
                "range": "-20~-18%",
                "count": 10,
                "ratio": 0.01,
            }
        ]
        * 20,
        "daily_trade_rows": [{"date": "2020-01-02", "buys": 1, "sells": 1}] * n_days,
        "selection_stats": {
            "signals_entry": 99999,
            "signals_exit": 88888,
            "filled_trades": n_trades,
        },
        "factor_attribution": {"fields": ["ma5"] * 50, "rows": [[0.1] * 50] * 100},
    }


class SummaryTest(unittest.TestCase):
    def test_summary_under_10kb_for_huge_result(self) -> None:
        result = big_position_result()
        self.assertGreater(len(dumps(result)), 1_000_000)  # 原始结果 MB 级
        summary = summarize(result)
        size = len(dumps(summary).encode("utf-8"))
        self.assertLessEqual(size, SUMMARY_MAX_BYTES)
        self.assertLessEqual(SUMMARY_MAX_BYTES, 10 * 1024)

    def test_summary_contract_fields(self) -> None:
        result = big_position_result(
            n_days=1000, n_trades=300, n_symbols=100, long_name="贵州茅台"
        )
        s = summarize(result)
        self.assertLessEqual(len(dumps(s).encode("utf-8")), SUMMARY_MAX_BYTES)
        self.assertEqual(s["strategy"], "ma_golden_cross")
        self.assertEqual(s["range"], ["2015-01-05", "2025-12-31"])
        self.assertEqual(s["trade_count"], 300)
        self.assertEqual(s["symbol_count"], 100)
        # 标量 stats 全保留（嵌套的 unadjusted 列表剔除）
        for key in (
            "total_return",
            "annual_return",
            "max_drawdown",
            "sharpe",
            "win_rate",
            "final_value",
        ):
            self.assertIn(key, s["stats"])
        self.assertNotIn("unadjusted", s["stats"])
        self.assertIn("exit_stats", s)
        self.assertEqual(s["execution_stats"]["skipped_max_positions"], 3456)
        self.assertEqual(s["benchmark"]["total_return"], 0.3)
        # 净值 ≤50 点且保留首尾
        self.assertLessEqual(len(s["equity_curve"]), 50)
        self.assertEqual(
            s["equity_curve"][0]["date"], result["equity_curve"][0]["date"]
        )
        self.assertEqual(
            s["equity_curve"][-1]["date"], result["equity_curve"][-1]["date"]
        )
        self.assertEqual(s["equity_curve_total"], 1000)
        # per_symbol 最好/最差各 10
        ps = s["per_symbol"]
        self.assertEqual(ps["total"], 100)
        self.assertEqual(len(ps["best"]), 10)
        self.assertEqual(len(ps["worst"]), 10)
        self.assertEqual(
            ps["best"][0]["total_return"],
            max(r["total_return"] for r in result["per_symbol_stats"]),
        )
        self.assertEqual(
            ps["worst"][0]["total_return"],
            min(r["total_return"] for r in result["per_symbol_stats"]),
        )
        best_syms = {r["symbol"] for r in ps["best"]}
        self.assertFalse(best_syms & {r["symbol"] for r in ps["worst"]})
        # unadjusted 数量与前 20
        self.assertEqual(s["unadjusted_count"], 100)
        self.assertEqual(s["unadjusted_head"], result["unadjusted"][:20])

    def test_extreme_names_shrink_text_not_counts(self) -> None:
        # 超长名称先收行内文本与卖出归因，契约条数（净值 50 点 / 最好最差各 10 / unadjusted 20）不变
        s = summarize(big_position_result(n_days=1000, n_trades=300, n_symbols=100))
        self.assertLessEqual(len(dumps(s).encode("utf-8")), SUMMARY_MAX_BYTES)
        self.assertEqual(len(s["equity_curve"]), 50)
        self.assertEqual(len(s["per_symbol"]["best"]), 10)
        self.assertEqual(len(s["unadjusted_head"]), 20)
        self.assertEqual(s["per_symbol"]["best"][0]["symbol"], "600099.SH")

    def test_full_mode_reads_nested_per_symbol(self) -> None:
        result = big_position_result(n_days=200, n_trades=50, n_symbols=30)
        nested = result.pop("per_symbol_stats")
        result["stats"] = {
            "mode": "full",
            "full_kind": "candidate_execution",
            "n_candidates": 80,
            "n_trades": 50,
            "total_return": 0.1,
            "per_symbol_stats": nested,
            "return_distribution": [],
        }
        s = summarize(result)
        self.assertEqual(s["mode"], "full")
        self.assertEqual(s["stats"]["n_candidates"], 80)
        self.assertEqual(s["per_symbol"]["total"], 30)
        self.assertEqual(len(section_items(result, "per_symbol")), 30)

    def test_minute_replay_summary(self) -> None:
        result = {
            "mode": "minute_replay",
            "strategy": "ai_minute",
            "symbols": ["600519.SH"],
            "range": ["2025-01-02", "2025-03-31"],
            "replayed_days": 58,
            "skipped_days": ["2025-01-10"],
            "buy_limit_up": 2,
            "unadjusted": [],
            "elapsed_ms": 1.0,
            "hits": [
                {
                    "trade_date": "2025-01-03",
                    "symbol": "600519.SH",
                    "entry_price": 1500.0,
                    "trigger_time": "10:31",
                    "score": 0.9,
                }
            ]
            * 300,
        }
        s = summarize(result)
        self.assertEqual(s["mode"], "minute_replay")
        self.assertEqual(s["hit_count"], 300)
        self.assertEqual(len(s["hits_head"]), 10)
        self.assertEqual(len(section_items(result, "trades")), 300)
        self.assertLessEqual(len(dumps(s).encode("utf-8")), SUMMARY_MAX_BYTES)

    def test_non_dict_result(self) -> None:
        self.assertIn("error", summarize(None))
        self.assertEqual(section_items(None, "trades"), [])


class DownsampleAndPaginateTest(unittest.TestCase):
    def test_downsample_keeps_endpoints(self) -> None:
        pts = list(range(1001))
        out = downsample(pts, 50)
        self.assertLessEqual(len(out), 50)
        self.assertEqual(out[0], 0)
        self.assertEqual(out[-1], 1000)
        self.assertEqual(out, sorted(out))
        self.assertEqual(downsample(pts[:10], 50), pts[:10])
        self.assertEqual(downsample(pts, 2), [0, 1000])

    def test_paginate(self) -> None:
        rows = list(range(123))
        page = paginate(rows, 100, 50)
        self.assertEqual(
            page,
            {"total": 123, "offset": 100, "limit": 50, "items": list(range(100, 123))},
        )
        self.assertEqual(paginate(rows, 500, 10)["items"], [])


if __name__ == "__main__":
    unittest.main()
