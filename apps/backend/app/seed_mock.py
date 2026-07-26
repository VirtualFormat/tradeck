"""dev 用假数据种子脚本（本地数据源被限流/封锁时填充 DB，方便看页面效果）

用法（dev 环境）：
    docker exec tradeck-dev-backend python -m app.seed_mock

- 覆盖 20 张表，全部 UPSERT，可重复执行
- 真数据到达后会被正常 job 覆盖（jobs 拉取失败返回 0 行，不会清掉假数据）
- 不要在 prod 跑
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.db import close_pool, get_pool
from app.jobs.daily_kline import TRACKED_SYMBOLS
from app.jobs.indices import TRACKED_COMMODITIES, TRACKED_INDICES
from app.markets import pick_market

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

rng = random.Random(42)

# ── 名称映射（A 股/港股给中文名，美股用代码兜底）──
NAMES: dict[str, str] = {
    "600519.SH": "贵州茅台", "601318.SH": "中国平安", "600036.SH": "招商银行",
    "000858.SZ": "五粮液", "002594.SZ": "比亚迪", "300750.SZ": "宁德时代",
    "601012.SH": "隆基绿能", "600900.SH": "长江电力", "000001.SZ": "平安银行",
    "601166.SH": "兴业银行", "600276.SH": "恒瑞医药", "601398.SH": "工商银行",
    "000333.SZ": "美的集团", "600030.SH": "中信证券", "601888.SH": "中国中免",
    "600031.SH": "三一重工", "000651.SZ": "格力电器", "002415.SZ": "海康威视",
    "300059.SZ": "东方财富", "600009.SH": "上海机场", "601628.SH": "中国人寿",
    "600585.SH": "海螺水泥", "000568.SZ": "泸州老窖", "002714.SZ": "牧原股份",
    "600436.SH": "片仔癀", "603259.SH": "药明康德", "601857.SH": "中国石油",
    "600028.SH": "中国石化", "601088.SH": "中国神华", "600019.SH": "宝钢股份",
    "00700.HK": "腾讯控股", "09988.HK": "阿里巴巴-SW", "01810.HK": "小米集团-W",
    "03690.HK": "美团-W", "09618.HK": "京东集团-SW", "00005.HK": "汇丰控股",
    "01299.HK": "友邦保险", "00883.HK": "中国海洋石油", "00939.HK": "建设银行",
    "02318.HK": "中国平安",
}

# ── 基准价（没列到的按市场随机）──
BASE_PRICE: dict[str, float] = {
    "600519.SH": 1480.0, "601318.SH": 52.0, "600036.SH": 38.0, "000858.SZ": 128.0,
    "002594.SZ": 245.0, "300750.SZ": 185.0, "601012.SH": 18.5, "600900.SH": 27.0,
    "000001.SZ": 11.5, "601166.SH": 19.0, "600276.SH": 46.0, "601398.SH": 6.8,
    "000333.SZ": 72.0, "600030.SH": 26.0, "601888.SH": 68.0, "600031.SH": 17.5,
    "000651.SZ": 41.0, "002415.SZ": 31.0, "300059.SZ": 22.0, "600009.SH": 34.0,
    "601628.SH": 38.0, "600585.SH": 24.0, "000568.SZ": 135.0, "002714.SZ": 42.0,
    "600436.SH": 205.0, "603259.SH": 62.0, "601857.SH": 9.2, "600028.SH": 6.1,
    "601088.SH": 38.0, "600019.SH": 6.9,
    "00700.HK": 520.0, "09988.HK": 118.0, "01810.HK": 42.0, "03690.HK": 128.0,
    "09618.HK": 135.0, "00005.HK": 88.0, "01299.HK": 68.0, "00883.HK": 19.0,
    "00939.HK": 7.2, "02318.HK": 48.0,
    "AAPL": 232.0, "MSFT": 505.0, "NVDA": 178.0, "TSLA": 248.0, "AMZN": 224.0,
    "GOOGL": 191.0, "META": 710.0, "NFLX": 1210.0, "AMD": 162.0, "INTC": 24.0,
}

INDEX_BASE: dict[str, float] = {
    "^GSPC": 6300.0, "^IXIC": 20800.0, "^DJI": 44800.0,
    "^HSI": 24500.0, "^HSCEI": 8900.0,
    "000001.SS": 3350.0, "399001.SZ": 10600.0, "399006.SZ": 2180.0,
    "GC=F": 3350.0, "CL=F": 68.0, "SI=F": 38.0, "BTC-USD": 118000.0,
    "^N225": 40000.0, "^STOXX50E": 5300.0, "^VIX": 17.0, "HG=F": 4.6,
}

PROFILE_SYMBOLS = ["AAPL", "MSFT", "NVDA", "600519.SH", "000001.SZ", "00700.HK"]

PROFILE_INFO: dict[str, dict] = {
    "AAPL": {"name": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics", "currency": "USD", "exchange": "NASDAQ"},
    "MSFT": {"name": "Microsoft Corporation", "sector": "Technology", "industry": "Software—Infrastructure", "currency": "USD", "exchange": "NASDAQ"},
    "NVDA": {"name": "NVIDIA Corporation", "sector": "Technology", "industry": "Semiconductors", "currency": "USD", "exchange": "NASDAQ"},
    "600519.SH": {"name": "贵州茅台", "sector": "Consumer Defensive", "industry": "白酒", "currency": "CNY", "exchange": "SSE"},
    "000001.SZ": {"name": "平安银行", "sector": "Financial Services", "industry": "银行", "currency": "CNY", "exchange": "SZSE"},
    "00700.HK": {"name": "腾讯控股", "sector": "Communication Services", "industry": "互联网内容", "currency": "HKD", "exchange": "HKEX"},
}

NEWS_TITLES = [
    "美联储官员暗示年内可能降息，美股三大指数齐涨",
    "英伟达新一代 AI 芯片订单爆满，台积电产能吃紧",
    "贵州茅台批价企稳回升，白酒板块午后拉升",
    "特斯拉二季度交付量超预期，盘后大涨 7%",
    "央行开展 5000 亿元 MLF 操作，利率持平",
    "苹果折叠屏 iPhone 供应链曝光，预计明年发布",
    "腾讯游戏暑期档流水创新高，新游表现亮眼",
    "OPEC+ 宣布延长减产协议，国际油价涨超 2%",
    "比亚迪 6 月新能源车销量再创纪录",
    "美国 6 月非农就业人数超预期，失业率小幅回落",
    "宁德时代发布新一代麒麟电池，续航突破 1000 公里",
    "微软 Copilot 企业版订阅数突破千万",
    "港交所拟下调特专科技公司上市门槛",
    "北向资金单日净流入超百亿，加仓白酒新能源",
    "亚马逊 AWS 推出自研 AI 训练芯片新款",
    "卫健委部署创新药支持政策，医药板块走强",
    "比特币突破 12 万美元关口，创近三个月新高",
    "Meta 加码元宇宙投入，Reality Labs 扩招两成",
    "国内 6 月 CPI 同比上涨 0.3%，PPI 降幅收窄",
    "高盛上调标普 500 年终目标位至 6600 点",
    "小米 SU7 月交付破两万，二期工厂提前投产",
    "礼来减肥药适应症扩大获批，股价创新高",
    "财政部宣布增发特别国债支持「两重」建设",
    "谷歌量子计算取得新突破，纠错效率提升十倍",
]

# 新闻可能关联的股票（让 /news?symbol= 有数据）
NEWS_SYMBOLS = ["AAPL", "NVDA", "TSLA", "MSFT", "META", "600519.SH", "300750.SZ", "002594.SZ", "00700.HK", "01810.HK"]

# 板块 mock（概念 40 + 行业 30，名称贴近东财）
CONCEPT_BOARDS = [
    "人工智能", "芯片概念", "算力租赁", "数据要素", "机器人概念", "低空经济",
    "固态电池", "新能源车", "锂电池", "储能", "光伏概念", "白酒概念",
    "军工", "稀土永磁", "ChatGPT概念", "AIGC概念", "CPO概念", "液冷服务器",
    "华为概念", "苹果概念", "特斯拉概念", "比亚迪概念", "宁德时代概念", "国产软件",
    "信创", "数字经济", "元宇宙", "网络游戏", "短剧游戏", "医药电商",
    "创新药", "CXO概念", "医疗器械", "养老概念", "三胎概念", "预制菜",
    "跨境电商", "免税概念", "一带一路", "中特估",
]
INDUSTRY_BOARDS = [
    "半导体", "银行", "证券", "保险", "白酒", "电池", "光伏设备", "软件开发",
    "通信设备", "医疗器械", "汽车整车", "汽车零部件", "房地产", "煤炭行业",
    "钢铁行业", "石油行业", "有色金属", "化工行业", "医药商业", "生物制品",
    "食品饮料", "家电行业", "纺织服装", "造纸印刷", "水泥建材", "工程建设",
    "电力行业", "港口航运", "航空机场", "旅游酒店",
]


def _weekdays(days: int) -> list[date]:
    """最近 N 天的交易日（周一到周五）。"""
    result = []
    d = date.today()
    while len(result) < days:
        if d.weekday() < 5:
            result.append(d)
        d -= timedelta(days=1)
    return sorted(result)


def _base_price(symbol: str, market: str) -> float:
    if symbol in BASE_PRICE:
        return BASE_PRICE[symbol]
    if market == "CN":
        return rng.uniform(8, 120)
    if market == "HK":
        return rng.uniform(15, 300)
    return rng.uniform(15, 400)


def _random_walk(base: float, days: int, final_close: float | None = None) -> list[float]:
    """生成 days 个收盘价，可选缩放到指定末值。"""
    prices = [base]
    for _ in range(days - 1):
        prices.append(prices[-1] * (1 + rng.gauss(0.0005, 0.018)))
    prices = [max(p, 0.01) for p in prices]
    if final_close:
        factor = final_close / prices[-1]
        prices = [p * factor for p in prices]
    return prices


async def seed_quotes(conn) -> dict[str, tuple[float, float]]:
    """写 quote_snapshots，返回 {symbol: (last_price, change_percent)} 供 K 线对齐。"""
    quotes: dict[str, tuple[float, float]] = {}
    rows = []
    for sym in TRACKED_SYMBOLS:
        market = pick_market(sym)
        # change_percent 存小数（0.0715 = 7.15%，与 yfinance/movers_cache 一致）
        # 正态分布 N(0, 2%) 截断 ±10%：强弱股占比接近真实市场（均匀分布会导致情绪指标极化）
        pct = max(-0.1, min(0.1, rng.gauss(0, 0.02)))
        price = round(_base_price(sym, market), 2)
        change = round(price * pct, 2)
        quotes[sym] = (price, pct)
        rows.append((
            sym, NAMES.get(sym, sym), price, change, round(pct, 6),
            rng.randint(1_000_000, 500_000_000), market,
        ))
    await conn.executemany(
        """
        INSERT INTO quote_snapshots
            (symbol, name, last_price, change, change_percent, volume, market, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
        ON CONFLICT (symbol) DO UPDATE SET
            name = EXCLUDED.name, last_price = EXCLUDED.last_price,
            change = EXCLUDED.change, change_percent = EXCLUDED.change_percent,
            volume = EXCLUDED.volume, market = EXCLUDED.market, updated_at = NOW()
        """,
        rows,
    )
    return quotes


async def seed_daily_prices(conn, quotes: dict[str, tuple[float, float]]) -> int:
    days = _weekdays(250)
    rows = []
    for sym, (last_price, _) in quotes.items():
        market = pick_market(sym)
        closes = _random_walk(last_price * rng.uniform(0.75, 0.95), len(days), last_price)
        prev = closes[0]
        for d, close in zip(days, closes):
            open_ = prev * (1 + rng.gauss(0, 0.004))
            high = max(open_, close) * (1 + abs(rng.gauss(0, 0.004)))
            low = min(open_, close) * (1 - abs(rng.gauss(0, 0.004)))
            rows.append((
                sym, market, d, round(open_, 2), round(high, 2),
                round(low, 2), round(close, 2), rng.randint(1_000_000, 300_000_000),
            ))
            prev = close
    await conn.executemany(
        """
        INSERT INTO daily_prices (symbol, market, date, open, high, low, close, volume)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (symbol, date) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
            close = EXCLUDED.close, volume = EXCLUDED.volume
        """,
        rows,
    )
    return len(rows)


async def seed_index_prices(conn) -> int:
    days = _weekdays(250)
    rows = []
    for item in TRACKED_INDICES + TRACKED_COMMODITIES:
        sym, market = item["symbol"], item["market"]
        base = INDEX_BASE.get(sym, 1000.0)
        # VIX 均值回归品种：锚定末值防随机游走漂出合理区间
        closes = _random_walk(base, len(days), base if sym == "^VIX" else None)
        for d, close in zip(days, closes):
            rows.append((sym, market, d, round(close, 2), rng.randint(0, 5_000_000_000)))
    await conn.executemany(
        """
        INSERT INTO index_prices (symbol, market, date, close, volume)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (symbol, date) DO UPDATE SET
            close = EXCLUDED.close, volume = EXCLUDED.volume
        """,
        rows,
    )
    return len(rows)


async def seed_movers(conn, quotes: dict[str, tuple[float, float]]) -> int:
    """美股涨跌榜（gainers/losers/active 各 10 条，全量覆盖式刷新）。"""
    us = [(s, price, pct) for s, (price, pct) in quotes.items() if pick_market(s) == "US"]
    gainers = sorted(us, key=lambda x: x[2], reverse=True)[:10]
    losers = sorted(us, key=lambda x: x[2])[:10]
    active = sorted(us, key=lambda x: abs(x[2]), reverse=True)[:10]
    await conn.execute("DELETE FROM movers_cache WHERE market = 'US'")
    rows = []
    for mtype, group in (("gainers", gainers), ("losers", losers), ("active", active)):
        for rank, (sym, price, pct) in enumerate(group, 1):
            rows.append((
                mtype, "US", rank, sym, NAMES.get(sym, sym), price,
                round(pct, 4), rng.randint(5_000_000, 800_000_000),
            ))
    await conn.executemany(
        """
        INSERT INTO movers_cache (type, market, rank, symbol, name, price, percent_change, volume, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
        """,
        rows,
    )
    return len(rows)


async def seed_news(conn) -> int:
    rows = []
    now = datetime.now(timezone.utc)
    for i, title in enumerate(NEWS_TITLES):
        sym = NEWS_SYMBOLS[i % len(NEWS_SYMBOLS)] if i % 2 == 0 else None
        rows.append((
            sym, title, f"https://mock.tradeck.dev/news/{i:03d}",
            f"{title}。（mock 摘要）本文由 dev 种子脚本生成，仅用于本地调试页面效果。",
            rng.choice(["华尔街见闻", "财联社", "彭博社", "路透中文网", "证券时报"]),
            now - timedelta(hours=i * 3 + rng.randint(0, 2)),
        ))
    await conn.executemany(
        """
        INSERT INTO news_articles (symbol, title, url, summary, publisher, published_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (url) DO UPDATE SET
            title = EXCLUDED.title, summary = EXCLUDED.summary,
            publisher = EXCLUDED.publisher, published_at = EXCLUDED.published_at
        """,
        rows,
    )
    return len(rows)


async def seed_macro(conn) -> int:
    days = _weekdays(120)
    monthly = [d for d in days if d.day <= 7][:12]  # 每月取一个代表日
    # 单位与真实源对齐：CPI/失业率/利率为小数（0.030 = 3.0%），GDP 为美元绝对值
    series = {
        "CPI": (0.030, 0.0015, monthly),
        "Unemployment": (0.041, 0.0008, monthly),
        "GDP_Nominal": (29_000_000_000_000.0, 150_000_000_000.0, monthly),
        "EFFR": (0.0487, 0.0005, days[-60:]),
        "SOFR": (0.0485, 0.0006, days[-60:]),
    }
    rows = []
    for name, (base, vol, dates) in series.items():
        for d in dates:
            rows.append((name, d, round(base + rng.gauss(0, vol), 4)))
    await conn.executemany(
        """
        INSERT INTO macro_indicators (name, date, value)
        VALUES ($1, $2, $3)
        ON CONFLICT (name, date) DO UPDATE SET value = EXCLUDED.value
        """,
        rows,
    )
    return len(rows)


async def seed_fundamentals(conn, quotes: dict[str, tuple[float, float]]) -> int:
    """equity_profiles + fundamental_metrics + income_statements（3 张表，几只代表股票）。"""
    profiles = []
    metrics = []
    income = []
    for sym in PROFILE_SYMBOLS:
        info = PROFILE_INFO[sym]
        price = quotes.get(sym, (BASE_PRICE.get(sym, 100.0), 0))[0]
        market_cap = int(price * rng.uniform(0.5, 20) * 1e9)
        profiles.append((
            sym, info["name"], info["sector"], info["industry"], market_cap,
            info["currency"], info["exchange"],
            f"{info['name']}（mock 简介）主营业务覆盖 {info['industry']} 领域，"
            f"本数据由 dev 种子脚本生成，仅用于本地调试页面效果。",
        ))
        metrics.append((
            sym, market_cap, round(rng.uniform(8, 45), 2), round(rng.uniform(8, 40), 2),
            round(rng.uniform(0.8, 3), 2), round(rng.uniform(8, 25), 2),
            round(rng.uniform(-0.05, 0.35), 4), round(rng.uniform(-0.02, 0.30), 4),
            round(rng.uniform(0, 0.03), 4), round(rng.uniform(0.5, 1.8), 2),
            round(rng.uniform(0.08, 0.45), 4), round(rng.uniform(0.05, 0.35), 4),
            round(rng.uniform(10, 150), 2),
        ))
        base_rev = market_cap * rng.uniform(0.15, 0.6)
        for i, fy in enumerate((2022, 2023, 2024)):
            rev = base_rev * (1 + 0.08 * i) * rng.uniform(0.95, 1.05)
            margin = rng.uniform(0.10, 0.30)
            income.append((
                sym, fy, round(rev, 2), round(rev * margin, 2),
                round(rev * rng.uniform(0.35, 0.6), 2), round(rev * margin * 1.2, 2),
            ))
    await conn.executemany(
        """
        INSERT INTO equity_profiles
            (symbol, name, sector, industry, market_cap, currency, exchange, description, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
        ON CONFLICT (symbol) DO UPDATE SET
            name = EXCLUDED.name, sector = EXCLUDED.sector, industry = EXCLUDED.industry,
            market_cap = EXCLUDED.market_cap, currency = EXCLUDED.currency,
            exchange = EXCLUDED.exchange, description = EXCLUDED.description, updated_at = NOW()
        """,
        profiles,
    )
    await conn.executemany(
        """
        INSERT INTO fundamental_metrics
            (symbol, market_cap, pe_ratio, forward_pe, peg_ratio, enterprise_to_ebitda,
             earnings_growth, revenue_growth, dividend_yield, beta, profit_margins,
             return_on_equity, debt_to_equity, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW())
        ON CONFLICT (symbol) DO UPDATE SET
            market_cap = EXCLUDED.market_cap, pe_ratio = EXCLUDED.pe_ratio,
            forward_pe = EXCLUDED.forward_pe, peg_ratio = EXCLUDED.peg_ratio,
            enterprise_to_ebitda = EXCLUDED.enterprise_to_ebitda,
            earnings_growth = EXCLUDED.earnings_growth, revenue_growth = EXCLUDED.revenue_growth,
            dividend_yield = EXCLUDED.dividend_yield, beta = EXCLUDED.beta,
            profit_margins = EXCLUDED.profit_margins, return_on_equity = EXCLUDED.return_on_equity,
            debt_to_equity = EXCLUDED.debt_to_equity, updated_at = NOW()
        """,
        metrics,
    )
    await conn.executemany(
        """
        INSERT INTO income_statements
            (symbol, fiscal_year, total_revenue, net_income, gross_profit, operating_income)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (symbol, fiscal_year) DO UPDATE SET
            total_revenue = EXCLUDED.total_revenue, net_income = EXCLUDED.net_income,
            gross_profit = EXCLUDED.gross_profit, operating_income = EXCLUDED.operating_income
        """,
        income,
    )
    return len(profiles) + len(metrics) + len(income)


async def seed_boards(conn) -> int:
    """板块行情热度 mock（board_heat，全量覆盖式）。"""
    cn_names = [s for s in TRACKED_SYMBOLS if pick_market(s) == "CN"]
    rows = []
    for btype, boards in (("concept", CONCEPT_BOARDS), ("industry", INDUSTRY_BOARDS)):
        for i, name in enumerate(boards):
            leader_sym = cn_names[i % len(cn_names)]
            rows.append((
                btype, name, f"BK{8000 + i}",
                round(max(-6.0, min(6.0, rng.gauss(0, 1.5))), 2),
                int(rng.uniform(2e10, 5e12)),
                round(rng.uniform(0.5, 8.0), 2),
                NAMES.get(leader_sym, leader_sym),
                round(max(-10.0, min(10.0, rng.gauss(0, 3.0))), 2),
            ))
    await conn.execute("DELETE FROM board_heat")
    await conn.executemany(
        """
        INSERT INTO board_heat
            (board_type, name, code, change_percent, market_cap,
             turnover_rate, leader_stock, leader_change, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
        """,
        rows,
    )
    return len(rows)


async def seed_analyst_consensus(conn, quotes: dict[str, tuple[float, float]]) -> int:
    """analyst_consensus（分析师共识/目标价，PROFILE_SYMBOLS 几只代表股票）。"""
    # 评级 → recommendation_mean 合理区间（1=强力买入 … 5=卖出）
    reco_choices = ["strong_buy", "buy", "buy", "buy", "hold", "hold", "sell"]
    mean_range = {
        "strong_buy": (1.1, 1.6), "buy": (1.7, 2.4),
        "hold": (2.6, 3.3), "sell": (3.6, 4.4),
    }
    rows = []
    for sym in PROFILE_SYMBOLS:
        info = PROFILE_INFO[sym]
        price = quotes.get(sym, (BASE_PRICE.get(sym, 100.0), 0))[0]
        reco = rng.choice(reco_choices)
        lo, hi = mean_range[reco]
        consensus_target = round(price * rng.uniform(0.95, 1.25), 2)
        rows.append((
            sym, reco, round(rng.uniform(lo, hi), 2), rng.randint(8, 45),
            round(price * rng.uniform(1.15, 1.45), 2),   # target_high
            round(price * rng.uniform(0.75, 0.95), 2),   # target_low
            consensus_target,
            round(consensus_target * rng.uniform(0.97, 1.03), 2),  # target_median
            price, info["currency"],
        ))
    await conn.executemany(
        """
        INSERT INTO analyst_consensus
            (symbol, recommendation, recommendation_mean, number_of_analysts,
             target_high, target_low, target_consensus, target_median,
             current_price, currency, fetched_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
        ON CONFLICT (symbol, snapshot_date) DO UPDATE SET
            recommendation = EXCLUDED.recommendation,
            recommendation_mean = EXCLUDED.recommendation_mean,
            number_of_analysts = EXCLUDED.number_of_analysts,
            target_high = EXCLUDED.target_high,
            target_low = EXCLUDED.target_low,
            target_consensus = EXCLUDED.target_consensus,
            target_median = EXCLUDED.target_median,
            current_price = EXCLUDED.current_price,
            currency = EXCLUDED.currency,
            fetched_at = NOW()
        """,
        rows,
    )
    return len(rows)


async def seed_balance_cash(conn, quotes: dict[str, tuple[float, float]]) -> int:
    """balance_sheets + cash_flow_statements（年度 4 期，PROFILE_SYMBOLS）。"""
    balance_rows = []
    cash_rows = []
    for sym in PROFILE_SYMBOLS:
        price = quotes.get(sym, (BASE_PRICE.get(sym, 100.0), 0))[0]
        market_cap = price * rng.uniform(0.5, 20) * 1e9
        base_assets = market_cap * rng.uniform(0.4, 1.5)
        base_income = market_cap * rng.uniform(0.02, 0.08)
        for i, fy in enumerate((2021, 2022, 2023, 2024)):
            fiscal_date = date(fy, 12, 31)
            # 资产负债表：规模随年份温和增长
            assets = base_assets * (1 + 0.08 * i) * rng.uniform(0.95, 1.05)
            liab = assets * rng.uniform(0.3, 0.7)
            equity = assets - liab
            current_assets = assets * rng.uniform(0.25, 0.55)
            balance_rows.append((
                sym, "annual", fiscal_date,
                round(assets, 2), round(liab, 2), round(equity, 2),
                round(current_assets, 2), round(liab * rng.uniform(0.35, 0.65), 2),
                round(current_assets * rng.uniform(0.15, 0.5), 2),   # 货币资金
                round(current_assets * rng.uniform(0.05, 0.3), 2),   # 存货
                round(current_assets * rng.uniform(0.1, 0.35), 2),   # 应收账款
                round(liab * rng.uniform(0.3, 0.65), 2),             # 总债务
                round(equity * rng.uniform(0.4, 0.9), 2),            # 留存收益
            ))
            # 现金流量表：capex/回购/分红为负（现金流出）
            income = base_income * (1 + 0.08 * i) * rng.uniform(0.9, 1.1)
            operating = income * rng.uniform(1.05, 1.5)
            capex = -operating * rng.uniform(0.15, 0.4)
            cash_rows.append((
                sym, "annual", fiscal_date,
                round(operating, 2),
                round(capex - operating * rng.uniform(0.02, 0.2), 2),  # 投资现金流
                round(-operating * rng.uniform(0.05, 0.4), 2),         # 筹资现金流
                round(capex, 2),
                round(operating + capex, 2),                           # 自由现金流
                round(income, 2),
                round(income * rng.uniform(0.2, 0.5), 2),              # 折旧摊销
                round(-operating * rng.uniform(0, 0.3), 2),            # 回购
                round(-income * rng.uniform(0, 0.4), 2),               # 分红
            ))
    await conn.executemany(
        """
        INSERT INTO balance_sheets
            (symbol, period, fiscal_date, total_assets, total_liabilities,
             total_equity, total_current_assets, total_current_liabilities,
             cash_and_equivalents, inventories, accounts_receivable,
             total_debt, retained_earnings, fetched_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW())
        ON CONFLICT (symbol, period, fiscal_date) DO UPDATE SET
            total_assets = EXCLUDED.total_assets,
            total_liabilities = EXCLUDED.total_liabilities,
            total_equity = EXCLUDED.total_equity,
            total_current_assets = EXCLUDED.total_current_assets,
            total_current_liabilities = EXCLUDED.total_current_liabilities,
            cash_and_equivalents = EXCLUDED.cash_and_equivalents,
            inventories = EXCLUDED.inventories,
            accounts_receivable = EXCLUDED.accounts_receivable,
            total_debt = EXCLUDED.total_debt,
            retained_earnings = EXCLUDED.retained_earnings,
            fetched_at = NOW()
        """,
        balance_rows,
    )
    await conn.executemany(
        """
        INSERT INTO cash_flow_statements
            (symbol, period, fiscal_date, operating_cash_flow, investing_cash_flow,
             financing_cash_flow, capital_expenditure, free_cash_flow, net_income,
             depreciation_amortization, share_repurchase, dividends_paid, fetched_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
        ON CONFLICT (symbol, period, fiscal_date) DO UPDATE SET
            operating_cash_flow = EXCLUDED.operating_cash_flow,
            investing_cash_flow = EXCLUDED.investing_cash_flow,
            financing_cash_flow = EXCLUDED.financing_cash_flow,
            capital_expenditure = EXCLUDED.capital_expenditure,
            free_cash_flow = EXCLUDED.free_cash_flow,
            net_income = EXCLUDED.net_income,
            depreciation_amortization = EXCLUDED.depreciation_amortization,
            share_repurchase = EXCLUDED.share_repurchase,
            dividends_paid = EXCLUDED.dividends_paid,
            fetched_at = NOW()
        """,
        cash_rows,
    )
    return len(balance_rows) + len(cash_rows)


async def seed_earnings_calendar(conn) -> int:
    """earnings_calendar（未来 20 天内的财报披露事件，美股/港股代表标的）。"""
    candidates = [s for s in TRACKED_SYMBOLS if pick_market(s) in ("US", "HK")]
    rng.shuffle(candidates)
    rows = []
    today = date.today()
    for i, sym in enumerate(candidates[:18]):
        report_date = today + timedelta(days=i + 1)  # 分散在未来 1~18 天
        rows.append((
            sym,
            report_date,
            rng.choice(["BMO", "AMC", "--"]),
            round(rng.uniform(0.2, 12.0), 2),
            "yfinance",
        ))
    await conn.executemany(
        """
        INSERT INTO earnings_calendar
            (symbol, report_date, session, eps_estimate, source, fetched_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        ON CONFLICT (symbol, report_date) DO UPDATE SET
            session = EXCLUDED.session,
            eps_estimate = EXCLUDED.eps_estimate,
            source = EXCLUDED.source,
            fetched_at = NOW()
        """,
        rows,
    )
    return len(rows)


# 宏观事件 mock 池（事件名、国家、重要性、预期/前值单位贴近真实口径）
ECONOMIC_EVENTS = [
    ("美国", "CPI 月率（季调后）", "高", "0.2%", "0.3%"),
    ("美国", "初请失业金人数", "中", "23.5万", "24.1万"),
    ("美国", "PPI 月率", "中", "0.2%", "0.1%"),
    ("美国", "零售销售月率", "高", "0.4%", "0.6%"),
    ("美国", "密歇根大学消费者信心指数", "中", "62.5", "61.8"),
    ("美国", "EIA 原油库存变动", "低", "-180万桶", "70万桶"),
    ("中国", "LPR 一年期报价", "高", "3.00%", "3.00%"),
    ("中国", "社会融资规模", "高", "2.2万亿", "1.8万亿"),
    ("中国", "城镇调查失业率", "中", "5.1%", "5.0%"),
    ("欧元区", "CPI 年率初值", "中", "2.1%", "2.0%"),
]


async def seed_economic_calendar(conn) -> int:
    """economic_calendar（未来 7 天宏观经济数据发布事件）。"""
    rows = []
    today = date.today()
    for i, (country, name, importance, forecast, previous) in enumerate(ECONOMIC_EVENTS):
        event_date = today + timedelta(days=i % 7)  # 分散在未来 7 天
        rows.append((
            event_date,
            f"{rng.choice(['08:30', '09:30', '10:00', '20:30', '21:45'])}",
            country,
            name,
            importance,
            None,  # 未公布，actual 留空
            forecast,
            previous,
            "baidu",
        ))
    await conn.executemany(
        """
        INSERT INTO economic_calendar
            (event_date, event_time, country, event_name, importance,
             actual, forecast, previous, source, fetched_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
        ON CONFLICT (event_date, event_name, country) DO UPDATE SET
            event_time = EXCLUDED.event_time,
            importance = EXCLUDED.importance,
            actual = EXCLUDED.actual,
            forecast = EXCLUDED.forecast,
            previous = EXCLUDED.previous,
            source = EXCLUDED.source,
            fetched_at = NOW()
        """,
        rows,
    )
    return len(rows)


# 公告 mock 池（类型贴近东财公告分类）
ANNOUNCEMENT_MOCKS = [
    ("业绩预告", "2026 年半年度业绩预告"),
    ("分红", "2025 年度利润分配实施公告"),
    ("重大事项", "关于重大合同签订的公告"),
    ("股东大会", "2025 年年度股东大会决议公告"),
    ("风险提示", "关于股票交易异常波动的风险提示公告"),
    ("回购", "关于以集中竞价交易方式回购股份的进展公告"),
    ("定期报告", "2026 年第一季度报告"),
    ("高管变动", "关于公司高级管理人员变更的公告"),
    ("增发", "向特定对象发行 A 股股票发行情况报告书"),
    ("质押", "关于控股股东部分股份质押的公告"),
]

# 研报 mock 池（机构/评级/标题贴近东财研报）
RESEARCH_MOCKS = [
    ("中金公司", "买入", "业绩超预期，龙头优势持续巩固"),
    ("中信证券", "买入", "毛利率环比改善，上调盈利预测"),
    ("华泰证券", "增持", "需求回暖信号明确，估值具备吸引力"),
    ("国泰君安", "增持", "渠道库存去化顺利，静待旺季催化"),
    ("招商证券", "买入", "新产能投放在即，成长逻辑强化"),
    ("广发证券", "中性", "短期业绩承压，关注成本端变化"),
    ("海通证券", "买入", "海外订单落地，打开第二增长曲线"),
    ("申万宏源", "增持", "现金流稳健，分红率有望提升"),
    ("兴业证券", "买入", "行业景气度回升，量价齐升可期"),
    ("东方证券", "中性", "竞争加剧压制盈利，维持观望"),
]


async def seed_announcements(conn) -> int:
    """announcements（tracked A 股公告，近 10 天分散）。"""
    cn_symbols = [s for s in TRACKED_SYMBOLS if pick_market(s) == "CN"]
    today = date.today()
    rows = []
    for i, (category, title) in enumerate(ANNOUNCEMENT_MOCKS):
        sym = cn_symbols[i % len(cn_symbols)]
        name = NAMES.get(sym, sym)
        rows.append((
            sym,
            f"{name}：{title}",
            category,
            today - timedelta(days=i),
            f"https://mock.tradeck.dev/announcement/{i:03d}.pdf",
        ))
    await conn.executemany(
        """
        INSERT INTO announcements
            (symbol, title, category, publish_date, url, fetched_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        ON CONFLICT (symbol, title, publish_date) DO UPDATE SET
            category = EXCLUDED.category,
            url = EXCLUDED.url,
            fetched_at = NOW()
        """,
        rows,
    )
    return len(rows)


async def seed_research_reports(conn) -> int:
    """research_reports（tracked A 股券商研报，近 60 天分散）。"""
    cn_symbols = [s for s in TRACKED_SYMBOLS if pick_market(s) == "CN"]
    today = date.today()
    rows = []
    for i, (org, rating, title) in enumerate(RESEARCH_MOCKS):
        sym = cn_symbols[(i * 3) % len(cn_symbols)]
        name = NAMES.get(sym, sym)
        rows.append((
            sym,
            f"{name}：{title}",
            org,
            rating,
            "食品饮料" if i % 2 == 0 else "电力设备",
            round(rng.uniform(5, 60), 2),    # eps_forecast
            round(rng.uniform(8, 45), 2),    # pe_forecast
            2026,                            # forecast_year
            today - timedelta(days=i * 6),
            f"https://mock.tradeck.dev/research/{i:03d}.pdf",
        ))
    await conn.executemany(
        """
        INSERT INTO research_reports
            (symbol, title, org, rating, industry,
             eps_forecast, pe_forecast, forecast_year, publish_date, url, fetched_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
        ON CONFLICT (symbol, title, publish_date) DO UPDATE SET
            org = EXCLUDED.org,
            rating = EXCLUDED.rating,
            industry = EXCLUDED.industry,
            eps_forecast = EXCLUDED.eps_forecast,
            pe_forecast = EXCLUDED.pe_forecast,
            forecast_year = EXCLUDED.forecast_year,
            url = EXCLUDED.url,
            fetched_at = NOW()
        """,
        rows,
    )
    return len(rows)


# 宏观资产 mock 基准价（与 MACRO_ASSETS 清单一一对应）
MACRO_ASSET_BASE: dict[str, tuple[str, str, float]] = {
    "DX-Y.NYB": ("美元指数", "fx", 98.5),
    "USDCNH": ("离岸人民币", "fx", 7.16),
    "RSP": ("标普500等权", "etf", 340.0),
    "SPY": ("标普500", "etf", 630.0),
    "IWM": ("罗素2000", "etf", 225.0),
    "QQQ": ("纳指100", "etf", 560.0),
    "IVE": ("标普500价值", "etf", 205.0),
    "XLK": ("科技板块", "etf", 260.0),
    "XLP": ("必需消费", "etf", 82.0),
}


async def seed_macro_asset_prices(conn) -> int:
    """macro_asset_prices（9 个宏观资产 × 250 个交易日随机游走）。"""
    days = _weekdays(250)
    rows = []
    for sym, (name, category, base) in MACRO_ASSET_BASE.items():
        # fx 波动小、etf 波动正常：按类别给不同波动率；锚定末值=基准价，让最新价比值口径稳定
        vol = 0.003 if category == "fx" else 0.012
        prices = [base]
        for _ in range(len(days) - 1):
            prices.append(max(0.01, prices[-1] * (1 + rng.gauss(0.0003, vol))))
        factor = base / prices[-1]
        prices = [p * factor for p in prices]
        for d, close in zip(days, prices):
            rows.append((sym, name, category, d, round(close, 4)))
    await conn.executemany(
        """
        INSERT INTO macro_asset_prices (symbol, name, category, date, close)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (symbol, date) DO UPDATE SET
            name = EXCLUDED.name, category = EXCLUDED.category,
            close = EXCLUDED.close, fetched_at = now()
        """,
        rows,
    )
    return len(rows)


async def seed_yield_curve_rates(conn) -> int:
    """yield_curve_rates（~250 天假曲线：短端锚定政策利率，长端缓动，10Y>2Y 正常形态）。"""
    days = _weekdays(250)
    rows = []
    # 各期限基准利率（小数，0.043 = 4.3%）与日内噪声
    tenors = [
        ("month_1", 0.0370), ("month_3", 0.0385), ("month_6", 0.0400),
        ("year_1", 0.0400), ("year_2", 0.0415), ("year_3", 0.0418),
        ("year_5", 0.0425), ("year_7", 0.0435), ("year_10", 0.0445),
        ("year_20", 0.0490), ("year_30", 0.0495),
    ]
    for i, d in enumerate(days):
        # 整体利率水平缓慢漂移（趋势项 + 噪声），保持期限间相对形态
        drift = 0.004 * (i / len(days)) + rng.gauss(0, 0.0008)
        row = [d]
        for _, base in tenors:
            row.append(round(base + drift + rng.gauss(0, 0.0003), 6))
        rows.append(tuple(row))
    await conn.executemany(
        """
        INSERT INTO yield_curve_rates
            (date, month_1, month_3, month_6, year_1, year_2, year_3,
             year_5, year_7, year_10, year_20, year_30)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        ON CONFLICT (date) DO UPDATE SET
            month_1 = EXCLUDED.month_1, month_3 = EXCLUDED.month_3,
            month_6 = EXCLUDED.month_6, year_1 = EXCLUDED.year_1,
            year_2 = EXCLUDED.year_2, year_3 = EXCLUDED.year_3,
            year_5 = EXCLUDED.year_5, year_7 = EXCLUDED.year_7,
            year_10 = EXCLUDED.year_10, year_20 = EXCLUDED.year_20,
            year_30 = EXCLUDED.year_30, fetched_at = now()
        """,
        rows,
    )
    return len(rows)


async def seed_market_breadth(conn) -> int:
    """market_breadth（近 5 个交易日 A 股涨跌家数序列）。"""
    days = _weekdays(5)
    rows = []
    for d in days:
        up = int(rng.gauss(2200, 700))
        down = int(rng.gauss(2400, 700))
        flat = rng.randint(80, 250)
        limit_up = rng.randint(30, 90)
        limit_down = rng.randint(5, 40)
        rows.append((
            d,
            "CN",
            up,
            down,
            flat,
            limit_up,
            limit_down,
            max(0, limit_up - rng.randint(0, 10)),   # real_limit_up（剔 ST）
            max(0, limit_down - rng.randint(0, 5)),  # real_limit_down（剔 ST）
            rng.randint(5, 30),
            # Decimal：float 传 NUMERIC 无标度列会存二进制长尾
            Decimal(str(round(rng.uniform(8, 18), 2))),  # activity_rate %
            "mock",
        ))
    await conn.executemany(
        """
        INSERT INTO market_breadth
            (date, market, up_count, down_count, flat_count,
             limit_up_count, limit_down_count,
             real_limit_up_count, real_limit_down_count,
             suspended_count, activity_rate, source, fetched_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
        ON CONFLICT (date, market) DO UPDATE SET
            up_count = EXCLUDED.up_count,
            down_count = EXCLUDED.down_count,
            flat_count = EXCLUDED.flat_count,
            limit_up_count = EXCLUDED.limit_up_count,
            limit_down_count = EXCLUDED.limit_down_count,
            real_limit_up_count = EXCLUDED.real_limit_up_count,
            real_limit_down_count = EXCLUDED.real_limit_down_count,
            suspended_count = EXCLUDED.suspended_count,
            activity_rate = EXCLUDED.activity_rate,
            source = EXCLUDED.source,
            fetched_at = NOW()
        """,
        rows,
    )
    return len(rows)


async def main() -> None:
    logger.info("=== seed mock data start ===")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            quotes = await seed_quotes(conn)
            counts = {
                "quote_snapshots": len(quotes),
                "daily_prices": await seed_daily_prices(conn, quotes),
                "index_prices": await seed_index_prices(conn),
                "movers_cache": await seed_movers(conn, quotes),
                "news_articles": await seed_news(conn),
                "macro_indicators": await seed_macro(conn),
                "fundamentals(3表)": await seed_fundamentals(conn, quotes),
                "analyst_consensus": await seed_analyst_consensus(conn, quotes),
                "balance+cash(2表)": await seed_balance_cash(conn, quotes),
                "board_heat": await seed_boards(conn),
                "earnings_calendar": await seed_earnings_calendar(conn),
                "economic_calendar": await seed_economic_calendar(conn),
                "announcements": await seed_announcements(conn),
                "research_reports": await seed_research_reports(conn),
                "market_breadth": await seed_market_breadth(conn),
                "macro_asset_prices": await seed_macro_asset_prices(conn),
                "yield_curve_rates": await seed_yield_curve_rates(conn),
            }
    for table, n in counts.items():
        logger.info(f"  {table}: {n} rows")
    await close_pool()
    logger.info("=== seed mock data done ===")


if __name__ == "__main__":
    asyncio.run(main())
