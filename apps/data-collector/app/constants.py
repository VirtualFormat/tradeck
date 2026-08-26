"""共享常量：TRACKED_SYMBOLS 单一事实源。

tracked 标的（100 只：美股 60 + A 股 30 + 港股 10）是报价/基本面/新闻/
日历等 job 的精选样本；日K 覆盖已扩至全市场，本列表不限制日K 范围。

collector 各 job 从这里引用；data-api 侧不 import 本模块——它从库表
（announcements / research_reports 等）反查 tracked 标的，库即事实。
"""

TRACKED_SYMBOLS = [
    # ── 美股科技（30）──
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX",
    "AMD", "INTC", "AVGO", "QCOM", "ADBE", "CRM", "ORCL", "CSCO",
    "ACN", "IBM", "NOW", "UBER", "LYFT", "SNAP", "PINS", "SHOP",
    # Block, Inc. 2025 更名 ticker：SQ → XYZ（SQ 已失效，yfinance 404）
    "XYZ", "PYPL", "COIN", "PLTR", "SNOW", "ZM",
    # ── 美股金融/消费/医疗（20）──
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "V", "MA", "AXP",
    "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "DIS", "KO", "PEP", "PG",
    # ── 美股能源/工业（10）──
    "XOM", "CVX", "COP", "SLB", "EOG", "BA", "CAT", "GE", "HON", "UPS",
    # ── A 股（30）──（沪市用 .SH，与 TickFlow/业界一致）
    "600519.SH", "601318.SH", "600036.SH", "000858.SZ", "002594.SZ",
    "300750.SZ", "601012.SH", "600900.SH", "000001.SZ", "601166.SH",
    "600276.SH", "601398.SH", "000333.SZ", "600030.SH", "601888.SH",
    "600031.SH", "000651.SZ", "002415.SZ", "300059.SZ", "600009.SH",
    "601628.SH", "600585.SH", "000568.SZ", "002714.SZ", "600436.SH",
    "603259.SH", "601857.SH", "600028.SH", "601088.SH", "600019.SH",
    # ── 港股（10）──（5 位补零，与 TickFlow/业界一致）
    "00700.HK", "09988.HK", "01810.HK", "03690.HK", "09618.HK",
    "00005.HK", "01299.HK", "00883.HK", "00939.HK", "02318.HK",
]
