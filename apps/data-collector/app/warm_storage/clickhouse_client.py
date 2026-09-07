"""ClickHouse 原生 HTTP 接口（8123）薄客户端。

只用 httpx（项目既有依赖），不引 clickhouse-driver / clickhouse-connect
（TCP 9000 + 重型依赖）。与项目现有 httpx 客户端（openbb_client）同一模式：
单进程 asyncio collector 内短生命周期 AsyncClient，一次请求一个上下文。

纪律（对应 AGENTS.md 三条铁律与优雅降级约定）：
- 任何网络/服务端异常都不冒泡：记 logger.error，execute 返回 False、
  insert_json_each_row 返回 False、ping 返回 False。
- 上层（minute_bars.replace_market_day）据此返回 (0, 错误摘要)，
  绝不影响 collector 的 PG/冷层主链路写入。

超时：连接 5s / 读 30s（分钟K 块插体量，给 CH 合并留余量），常量可配。
重试：幂等/可重放请求重试 1 次（间隔 0.5s 退避）；客户端 4xx 视为
语义错误不重试。仅 GET ping 与 INSERT 重试；ALTER ... DELETE mutation
不重试（非纯幂等请求，失败留给下一轮 replace 重做删+插）。
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx

logger = logging.getLogger(__name__)

# 超时常量（秒）：连接 / 读。调用方可按需覆盖。
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0

# 重试：除首次外的额外尝试次数与退避间隔
MAX_RETRIES = 1
RETRY_BACKOFF_SECONDS = 0.5


def _error_digest(resp: httpx.Response) -> str:
    """从 CH 错误响应提取可读摘要（状态码 + 前 200 字节正文）。"""
    body = resp.text[:200] if resp.text else ""
    return f"HTTP {resp.status_code}: {body}".rstrip(": ")


class ClickHouseClient:
    """ClickHouse HTTP 接口异步客户端（薄封装，永不抛异常）。"""

    def __init__(
        self,
        base_url: str,
        database: str,
        *,
        connect_timeout: float = CONNECT_TIMEOUT,
        read_timeout: float = READ_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._database = database
        self._timeout = httpx.Timeout(read_timeout, connect=connect_timeout)

    async def _request(
        self,
        method: str,
        *,
        content: bytes | None = None,
        params: dict[str, str] | None = None,
        allow_retry: bool,
    ) -> tuple[bool, str]:
        """发一次（至多 1 次重试）HTTP 请求。

        返回 (成功与否, 错误摘要)。成功时错误摘要为空串；失败时
        错误摘要非空、用于上层降级日志。任何异常都在此消化。
        """
        attempts = MAX_RETRIES + 1 if allow_retry else 1
        last_error = ""
        for attempt in range(attempts):
            if attempt > 0:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.request(
                        method,
                        self._base_url,
                        content=content,
                        params=params,
                    )
            except Exception as exc:  # 连接拒绝/超时/DNS 等，全部降级
                last_error = f"{type(exc).__name__}: {exc}"
                logger.error(
                    "ClickHouse %s 请求异常（attempt %d/%d）: %s",
                    method,
                    attempt + 1,
                    attempts,
                    last_error,
                )
                continue
            if resp.status_code == 200:
                return True, ""
            last_error = _error_digest(resp)
            logger.error(
                "ClickHouse %s 返回非 200（attempt %d/%d）: %s",
                method,
                attempt + 1,
                attempts,
                last_error,
            )
            # 4xx 是 SQL 语义/参数错误，重试无意义，直接退出
            if 400 <= resp.status_code < 500:
                break
        return False, last_error

    async def ping(self) -> bool:
        """健康检查（SELECT 1）。失败返回 False，不抛。"""
        ok, _ = await self._request(
            "GET", params={"query": "SELECT 1"}, allow_retry=True
        )
        return ok

    async def execute(
        self, sql: str, *, params: dict[str, str] | None = None
    ) -> bool:
        """执行一条 SQL（DDL/ALTER 等无返回体语句）。

        params 走 CH HTTP 的 {name:Type} 占位符语法：SQL 内写 {m:String}，
        此处把 {"m": v} 映射为 param_m=v 查询参数，避免手工转义拼 SQL。
        ALTER mutation 不重试（见模块 docstring）。
        """
        query_params = {"query": sql, "database": self._database}
        if params:
            query_params.update({f"param_{k}": v for k, v in params.items()})
        ok, _ = await self._request("POST", params=query_params, allow_retry=False)
        return ok

    async def insert_json_each_row(self, table: str, rows: list[dict]) -> bool:
        """按 JSONEachRow 格式批量插入。

        rows 须已按表 schema 序列化好（本层只负责 JSON 编码与传输）。
        INSERT 幂等可重放，允许 1 次重试。空列表直接成功（无操作）。
        """
        if not rows:
            return True
        body = (
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
        )
        query_params = {
            "query": f"INSERT INTO {table} FORMAT JSONEachRow",
            "database": self._database,
        }
        ok, _ = await self._request(
            "POST", content=body.encode("utf-8"), params=query_params, allow_retry=True
        )
        return ok
