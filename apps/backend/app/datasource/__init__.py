"""数据层薄门面：横切能力（限流/重试/降级/路由）收口一处。

- akshare：进程级全局限流 + 退避重试（call_akshare）
- OpenBB：fetch_openbb（含海外节点分流）
- TickFlow：日K（阶段 2 引入 tickflow_source）
"""
from app.datasource.akshare_source import call_akshare
from app.datasource.openbb_source import fetch_openbb

__all__ = ["call_akshare", "fetch_openbb"]
