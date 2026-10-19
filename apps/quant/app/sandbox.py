"""策略沙箱 — 用户策略代码（custom/ai）的子进程执行环境（docs/MCP.md「轻量沙箱」）。

威胁模型：validator 是纯 AST 白名单，挡不住 numpy/polars 自身的能力（ctypes 任意
libc 调用、读写任意文件）。因此用户代码只允许在本模块拉起的子进程里执行：

- 干净环境：子进程环境变量从白名单重建（AI_API_KEY / SERVICE_TOKEN /
  INBOUND_SERVICE_TOKENS 等密钥不进子进程）。
- 降权：Popen(user=/group=/extra_groups=[]) 在 exec 前切到 QUANT_SANDBOX_UID
  （默认 65534 nobody），读不到 root 父进程的 /proc/<pid>/environ。
- 资源闸：禁止写普通文件（RLIMIT_FSIZE=0）、禁 core dump；独立进程组，
  取消/超时整组 SIGKILL。
- 回传协议：子进程 → 父进程只走 JSON 行（绝不 pickle）——被攻破的子进程
  可以伪造任意消息，pickle 反序列化等于在父进程（root + 全部密钥）执行代码。
  父进程 → 子进程方向用 pickle（子进程信任父进程，安全）。

已知边界（小范围可接受）：子进程仍可访问网络、可读全部缓存；写坏的策略
可占满 worker 池（由调用方超时兜底）。后续收紧方向见 docs/MCP.md。

本模块顶层只依赖标准库：子进程入口 `python -m app.sandbox` 在读取环境之前
不得 import app.config（否则配置单例会带着父进程的值被构造）。
"""
from __future__ import annotations

import json
import math
import os
import pickle
import signal
import subprocess
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

# 子进程环境变量白名单：只保留运行所需的非密钥项
_ENV_KEEP = (
    "PATH", "LANG", "LC_ALL", "TZ",
    "QUANT_CACHE_DIR", "QUANT_DEFAULT_USER",
    # 矩阵 dtype 回退开关（float32 默认 / float64 对拍用），非密钥
    "QUANT_MATRIX_DTYPE",
    "PYTHONHASHSEED", "PYTHONIOENCODING",
    # 线程数：polars/numpy 在受限环境下的线程池规模
    "POLARS_MAX_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
)

# 单条回传消息上限：防被攻破的子进程以超大 JSON 撑爆父进程内存。
# json.loads + 日期还原的峰值内存约为行大小的数倍到二十余倍（review 实测），
# 相对 quant 2g mem_limit 取 32MB；正常回测结果（逐日净值 + 交易明细）远小于此。
_MAX_MESSAGE_BYTES = 32 * 1024 * 1024
# 子进程 stderr 回收上限（告警日志转发到父进程 logger）
_STDERR_KEEP_BYTES = 64 * 1024

# 错误回显上限：便于 agent 自修，又不成为大块数据外带通道
ERROR_ECHO_LIMIT = 2048

# 日期/时间在 JSON 协议中的标记键（单键 dict，父进程解码还原）
_DATE_KEY = "__date__"
_DATETIME_KEY = "__datetime__"


class SandboxError(RuntimeError):
    """沙箱子进程失败（异常/崩溃/协议错误）。"""


class SandboxCancelled(RuntimeError):
    """沙箱任务被调用方取消（进程组已被杀）。"""


class SandboxViolation(RuntimeError):
    """主进程试图直接执行用户策略代码（应改走沙箱子进程）。"""


def truncate_error(message: str, limit: int = ERROR_ECHO_LIMIT) -> str:
    """错误文案截断（对外回显统一口径）。"""
    text = str(message)
    if len(text) <= limit:
        return text
    return text[:limit] + f"…（已截断，共 {len(text)} 字符）"


# ---------------------------------------------------------------------------
# JSON 协议编解码
# ---------------------------------------------------------------------------


def _to_jsonable(obj: Any) -> Any:
    """结果 → JSON 友好结构（子进程侧）。

    date/datetime 打标记以便父进程还原；numpy 标量/数组转原生；非有限浮点转 None
    （stats 等结果在入库/响应前本就要求 JSON 安全，NaN/Inf 没有合法 JSON 表示）。
    """
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, datetime):
        return {_DATETIME_KEY: obj.isoformat()}
    if isinstance(obj, date):
        return {_DATE_KEY: obj.isoformat()}
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_to_jsonable(v) for v in obj]
    item = getattr(obj, "item", None)  # numpy 标量
    if callable(item) and getattr(obj, "shape", None) == ():
        return _to_jsonable(item())
    tolist = getattr(obj, "tolist", None)  # numpy 数组
    if callable(tolist):
        return _to_jsonable(tolist())
    return str(obj)


def _from_jsonable(obj: Any) -> Any:
    """JSON 结构 → 结果（父进程侧，只还原日期标记，不构造任何其他类型）。"""
    if isinstance(obj, dict):
        if len(obj) == 1:
            if _DATE_KEY in obj and isinstance(obj[_DATE_KEY], str):
                return date.fromisoformat(obj[_DATE_KEY])
            if _DATETIME_KEY in obj and isinstance(obj[_DATETIME_KEY], str):
                return datetime.fromisoformat(obj[_DATETIME_KEY])
        return {k: _from_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_jsonable(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# 父进程：拉起子进程并收消息
# ---------------------------------------------------------------------------


def _sandbox_env() -> dict[str, str]:
    """子进程环境：白名单透传 + 缓存/默认用户取父进程当前 settings 值。

    取 settings 而非 os.environ：调用方（含测试）可能在进程内改过 settings，
    子进程必须看到同一份缓存目录。
    """
    from app.config import settings

    env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
    env["QUANT_CACHE_DIR"] = str(settings.QUANT_CACHE_DIR)
    env["QUANT_DEFAULT_USER"] = str(settings.QUANT_DEFAULT_USER)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _package_root() -> str:
    """app/ 包的父目录：子进程以此为 cwd，`-m app.sandbox` 经 sys.path[0]=cwd 导入。"""
    return str(Path(__file__).resolve().parent.parent)


def _sandbox_uid() -> int:
    """降权 uid（取 settings.QUANT_SANDBOX_UID）。"""
    from app.config import settings

    return int(settings.QUANT_SANDBOX_UID)


def _apply_child_limits() -> None:
    """子进程最先执行（已降权、加载任何业务代码之前）：资源闸只降不升。

    非特权进程无法再调高 hard limit，用户代码之后也解不开。
    """
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # 禁止写普通文件（write/truncate 超限即 EFBIG/SIGXFSZ）；管道写不受 RLIMIT_FSIZE 约束
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def run_sandboxed(
    kind: str,
    payload: dict[str, Any],
    progress_cb: Callable[[dict], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    timeout: float | None = None,
) -> Any:
    """在沙箱子进程内执行一个任务并返回结果（同步阻塞，调用方自行放线程）。

    kind：子进程侧分派键（见 _HANDLERS）。payload 经 pickle 送入子进程。
    子进程失败抛 SandboxError；cancel_check() 为真时整组杀并抛 SandboxCancelled；
    超时整组杀并抛 TimeoutError。
    """
    read_fd, write_fd = os.pipe()
    # -E 忽略 PYTHON* 环境变量；-B 不写 .pyc（子进程禁写文件）
    cmd = [sys.executable, "-E", "-B", "-m", "app.sandbox", str(write_fd)]
    uid = _sandbox_uid()
    kwargs: dict[str, Any] = {}
    if uid > 0 and os.geteuid() == 0:
        kwargs.update(user=uid, group=uid, extra_groups=[])
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=_sandbox_env(),
            cwd=_package_root(),
            pass_fds=(write_fd,),
            close_fds=True,
            start_new_session=True,  # 独立进程组：取消/超时整组杀
            **kwargs,
        )
    except BaseException:
        # Popen 失败（fork ENOMEM / pids 上限 / 降权失败等）：读端尚无人接管，必须在此关闭
        os.close(read_fd)
        raise
    finally:
        os.close(write_fd)

    stderr_chunks: list[bytes] = []

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        total = 0
        for chunk in iter(lambda: proc.stderr.read(8192), b""):
            if total < _STDERR_KEEP_BYTES:
                stderr_chunks.append(chunk)
            total += len(chunk)

    def _feed_stdin() -> None:
        # 独立线程写任务：payload 超过管道缓冲时 dump 会阻塞，不能卡住取消/超时检查
        assert proc.stdin is not None
        try:
            pickle.dump({"kind": kind, "payload": payload}, proc.stdin,
                        protocol=pickle.HIGHEST_PROTOCOL)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass  # 子进程已退出：按无终态消息处理

    result_box: dict[str, Any] = {}
    threads = [
        threading.Thread(target=_drain_stderr, daemon=True),
        threading.Thread(target=_feed_stdin, daemon=True),
    ]
    reader = threading.Thread(
        target=_read_messages, args=(read_fd, progress_cb, result_box), daemon=True,
    )
    for t in (*threads, reader):
        t.start()

    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        while reader.is_alive():
            reader.join(timeout=0.1)
            if cancel_check is not None and cancel_check():
                _kill_group(proc)
                raise SandboxCancelled("任务已被取消")
            if deadline is not None and time.monotonic() > deadline:
                _kill_group(proc)
                raise TimeoutError(f"沙箱任务超时（{timeout:g}s）")
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            proc.wait(timeout=5)
        threads[0].join(timeout=1)
        _forward_child_logs(kind, stderr_chunks)
        if "error" in result_box:
            raise SandboxError(result_box["error"])
        if "result" in result_box:
            return result_box["result"]
        tail = b"".join(stderr_chunks).decode("utf-8", "replace")[-ERROR_ECHO_LIMIT:]
        raise SandboxError(
            f"沙箱子进程未返回结果即退出（exitcode={proc.returncode}）"
            + (f"\n{tail}" if tail.strip() else "")
        )
    finally:
        if proc.poll() is None:
            _kill_group(proc)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        threads[0].join(timeout=1)
        for stream in (proc.stdin, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass


def _forward_child_logs(kind: str, chunks: list[bytes]) -> None:
    """子进程 stderr（WARNING 及以上日志）转写父进程 logger，便于 docker logs 排查。

    只取尾部、按行截断，防日志刷屏；内容来自用户代码可控进程，只作文本记录。
    """
    if not chunks:
        return
    import logging

    text = b"".join(chunks).decode("utf-8", "replace").strip()
    if not text:
        return
    log = logging.getLogger("app.sandbox.child")
    for line in text.splitlines()[-50:]:
        log.warning("[sandbox:%s] %s", kind, line[:500])


def _read_messages(read_fd: int, progress_cb, box: dict[str, Any]) -> None:
    """读线程：逐行解析 JSON 消息，直到终态消息或 EOF（读端 fd 由本线程关闭）。"""
    with os.fdopen(read_fd, "rb") as raw:
        for line in iter(lambda: raw.readline(_MAX_MESSAGE_BYTES + 1), b""):
            if len(line) > _MAX_MESSAGE_BYTES:
                box["error"] = "沙箱回传消息超出上限，已丢弃"
                return
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                box["error"] = "沙箱回传消息格式非法"
                return
            if not isinstance(msg, dict):
                box["error"] = "沙箱回传消息格式非法"
                return
            mtype = msg.get("type")
            if mtype == "progress":
                if progress_cb is not None and isinstance(msg.get("payload"), dict):
                    try:
                        progress_cb(_from_jsonable(msg["payload"]))
                    except Exception:  # 进度回调失败不影响主流程
                        pass
            elif mtype == "result":
                box["result"] = _from_jsonable(msg.get("payload"))
                return
            elif mtype == "error":
                box["error"] = truncate_error(str(msg.get("message") or "未知错误"))
                return


# ---------------------------------------------------------------------------
# 子进程：入口与任务分派
# ---------------------------------------------------------------------------


def _handle_backtest(payload: dict, emit_progress) -> dict:
    from app.worker import execute_backtest_task

    return execute_backtest_task(payload, emit_progress)


def _handle_screen(payload: dict, emit_progress) -> dict:
    from app.runner import user_strategy_dirs
    from app.screener import screen
    from app.strategy import StrategyRegistry

    reg = StrategyRegistry(user_strategy_dirs(payload.get("user_id")), user_id=payload.get("user_id"))
    end = payload.get("end_date")
    res = screen(
        payload["strategy_id"], payload.get("symbols"),
        end_date=date.fromisoformat(end) if end else None,
        params=payload.get("params"), registry=reg,
    )
    return {
        "strategy_id": res.strategy_id,
        "as_of": res.as_of,
        "rows": [
            {"symbol": r.symbol, "name": r.name, "score": r.score,
             "entry": r.signals["entry"], "exit": r.signals["exit"], "market": r.market}
            for r in res.rows
        ],
        "total": res.total,
        "unadjusted": res.unadjusted,
    }


def _handle_trial(payload: dict, emit_progress) -> dict:
    """试加载：加载单个策略文件 + 合成矩阵跑一次 compute 校验信号形状。"""
    from app.strategy.loader import trial_run_strategy_file

    return trial_run_strategy_file(
        Path(payload["path"]), payload.get("source", "custom"),
        user_id=payload.get("user_id"),
        extra_dirs=payload.get("extra_dirs"),
    )


def _handle_selftest(payload: dict, emit_progress) -> Any:
    """沙箱自检：固定行为，不执行任何用户代码（测试与上线验收用）。

    mode：probe（回报 uid/环境变量名/能否写缓存目录）/ progress（发两条进度后返回）/
    spin（死循环等父进程杀）/ crash（硬退出不回传）/ error（抛异常）/ big（超大结果）。
    """
    mode = payload.get("mode")
    if mode == "probe":
        cache = os.environ.get("QUANT_CACHE_DIR", "")
        target = Path(cache) / f".sandbox-probe-{os.getpid()}"
        try:
            target.write_text("x", encoding="utf-8")
            can_write = True
            target.unlink()
        except (OSError, Exception):
            can_write = False
        try:
            Path("/proc/1/environ").read_bytes()
            can_read_init_environ = True
        except OSError:
            can_read_init_environ = False
        return {
            "uid": os.getuid(),
            "env_keys": sorted(os.environ),
            "can_write_cache": can_write,
            "can_read_init_environ": can_read_init_environ,
            "today": date.today(),
        }
    if mode == "progress":
        emit_progress({"day": 1, "total": 2, "date": "2026-01-05"})
        emit_progress({"day": 2, "total": 2, "date": "2026-01-06"})
        return {"stats": {"trades": 0}}
    if mode == "spin":
        import time

        emit_progress({"day": 1, "total": 999, "date": "2026-01-05"})
        while True:  # pragma: no cover — 靠父进程杀
            time.sleep(0.05)
    if mode == "crash":
        os._exit(3)
    if mode == "error":
        raise ValueError("selftest 预期异常")
    raise ValueError(f"未知 selftest 模式：{mode!r}")


_HANDLERS: dict[str, Callable[[dict, Callable[[dict], None]], Any]] = {
    "backtest": _handle_backtest,
    "screen": _handle_screen,
    "trial": _handle_trial,
    "selftest": _handle_selftest,
}


def _child_main(write_fd: int) -> None:
    _apply_child_limits()
    import logging

    # WARNING 及以上写 stderr（父进程回收转写 logger）：策略降级为空信号、缓存缺失等
    # 告警在沙箱化后仍可在容器日志中排查
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    out = os.fdopen(write_fd, "wb", buffering=0)
    lock = threading.Lock()

    def _emit(msg: dict) -> None:
        data = json.dumps(_to_jsonable(msg), ensure_ascii=False, allow_nan=False).encode("utf-8")
        with lock:
            out.write(data + b"\n")

    try:
        task = pickle.load(sys.stdin.buffer)
        handler = _HANDLERS.get(task.get("kind"))
        if handler is None:
            raise ValueError(f"不支持的沙箱任务类型：{task.get('kind')!r}")
        result = handler(task.get("payload") or {}, lambda p: _emit({"type": "progress", "payload": p}))
        _emit({"type": "result", "payload": result})
    except BaseException as exc:  # noqa: BLE001 — 子进程内任何异常都结构化回传
        try:
            _emit({"type": "error", "message": f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__})
        except BaseException:
            pass
    finally:
        try:
            out.close()
        except OSError:
            pass
        os._exit(0)


if __name__ == "__main__":
    _child_main(int(sys.argv[1]))
