"""quant HTTP 服务入口（uvicorn app.main:app，单进程纪律）。"""
from __future__ import annotations

import logging

from app.api import app

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

__all__ = ["app"]
