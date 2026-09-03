"""数据层薄门面：横切能力（限流/重试/降级/路由）收口一处。

- akshare：进程级全局限流 + 退避重试（call_akshare）
- OpenBB：fetch_openbb（含海外节点分流）
- TickFlow：日K（阶段 2 引入 tickflow_source）
- findb：A 股主数据源（findb_source）
- 同花顺（hithink-finance）：A 股官方源（hithink_source）
- AmazingData（银河星耀数智）：A 股官方源兜底（amazingdata_source，x86-64 only）
"""
from app.datasource.akshare_source import call_akshare
from app.datasource.hithink_source import hithink_get
from app.datasource.openbb_source import fetch_openbb

__all__ = ["call_akshare", "fetch_openbb", "hithink_get"]
