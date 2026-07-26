"""OpenBB 薄门面：再导出 fetch_openbb（含海外节点分流）。

薄包一层，统一数据层入口；未来可在此加横切（超时/重试/指标），
现阶段几乎直通。
"""
from __future__ import annotations

from app.openbb_client import fetch_openbb

__all__ = ["fetch_openbb"]
