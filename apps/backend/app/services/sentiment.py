"""中文金融新闻情绪打分（L1 关键词词典法）

score_news(title, summary) -> float（-1..1）
标题权重 ×2、摘要 ×1；正负词抵消后归一化到 [-1, 1]。
后续可平滑替换为 LLM 打分（签名不变）。
"""
from __future__ import annotations

# 利好词（+1）
POSITIVE_WORDS = [
    "涨停", "大涨", "飙升", "创新高", "创阶段新高", "突破", "中标", "获批",
    "超预期", "预增", "预盈", "扭亏", "大增", "增长", "翻倍", "利好",
    "回购", "增持", "净流入", "加仓", "扩产", "满产", "订单饱满", "签约",
    "分红", "派息", "涨价", "回暖", "复苏", "新高", "上调评级", "买入评级",
    "超预期增长", "业绩亮眼", "创纪录", "新高纪录",
]

# 利空词（-1）
NEGATIVE_WORDS = [
    "跌停", "大跌", "暴跌", "创新低", "下滑", "亏损", "预亏", "预减",
    "处罚", "罚款", "立案", "问询", "警示函", "减持", "抛售", "净流出",
    "爆雷", "退市", "戴帽", "ST", "低于预期", "下调评级", "卖出评级",
    "违约", "逾期", "债务", "诉讼", "仲裁", "冻结", "腰斩", "缩水",
    "停产", "限产", "降价", "衰退", "风险警示",
]


def score_news(title: str | None, summary: str | None = None) -> float:
    """关键词法情绪打分，返回 -1..1。无命中返回 0。"""
    title = title or ""
    summary = summary or ""

    def count_hits(text: str, words: list[str]) -> int:
        return sum(text.count(w) for w in words)

    # 标题权重 ×2，摘要 ×1
    pos = count_hits(title, POSITIVE_WORDS) * 2 + count_hits(summary, POSITIVE_WORDS)
    neg = count_hits(title, NEGATIVE_WORDS) * 2 + count_hits(summary, NEGATIVE_WORDS)

    total = pos + neg
    if total == 0:
        return 0.0
    return round(max(-1.0, min(1.0, (pos - neg) / total)), 3)
