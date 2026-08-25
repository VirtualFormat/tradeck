"""选股执行：全市场扫描 + 排序。"""

from app.screener.executor import ScreenResult, ScreenRow, screen

__all__ = ["screen", "ScreenResult", "ScreenRow"]
