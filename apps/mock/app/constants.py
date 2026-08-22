"""共享常量副本：TRACKED_SYMBOLS / 指数与大宗商品清单。

⚠️ 本文件与 apps/data-collector/app/constants.py 保持同步：
TRACKED_SYMBOLS 的单一事实源在 data-collector，此处为 mock seed 独立容器
的只读副本；修改时两侧需一起更新。TRACKED_INDICES / TRACKED_COMMODITIES
源自 apps/data-collector/app/jobs/indices.py，同样需保持同步。
"""

TRACKED_SYMBOLS = [
    # ── 美股科技（30）──
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX",
    "AMD", "INTC", "AVGO", "QCOM", "ADBE", "CRM", "ORCL", "CSCO",
    "ACN", "IBM", "NOW", "UBER", "LYFT", "SNAP", "PINS", "SHOP",
    "SQ", "PYPL", "COIN", "PLTR", "SNOW", "ZM",
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

# 跟踪的指数（与 apps/data-collector/app/jobs/indices.py 保持同步）
TRACKED_INDICES = [
    {"symbol": "^GSPC", "market": "US"},
    {"symbol": "^IXIC", "market": "US"},
    {"symbol": "^DJI", "market": "US"},
    {"symbol": "^HSI", "market": "HK"},
    {"symbol": "^HSCEI", "market": "HK"},
    {"symbol": "000001.SS", "market": "CN"},
    {"symbol": "399001.SZ", "market": "CN"},
    {"symbol": "399006.SZ", "market": "CN"},
    {"symbol": "^N225", "market": "JP"},  # 日经 225
    {"symbol": "^STOXX50E", "market": "EU"},  # 欧洲斯托克 50
    {"symbol": "^VIX", "market": "VOL"},  # 恐慌指数
]

# 大宗商品（与 apps/data-collector/app/jobs/indices.py 保持同步）
TRACKED_COMMODITIES = [
    {"symbol": "GC=F", "market": "US"},  # 黄金
    {"symbol": "CL=F", "market": "US"},  # 原油
    {"symbol": "SI=F", "market": "US"},  # 白银
    {"symbol": "BTC-USD", "market": "US"},  # 比特币
    {"symbol": "HG=F", "market": "US"},  # 铜
]
