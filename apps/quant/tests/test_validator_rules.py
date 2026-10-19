"""validator 修正（docs/MCP.md P0）单测。

覆盖点：
- 双下划线名称：__builtins__ 下标取 exec、__name__ 赋值/自测块、dunder 定义均拒；
  单下划线私有工具函数照常放行。
- 平台注入键 params["__user_factor_values__"] 放行，其余 dunder 下标仍拒。
- scoring：本人 active 用户因子 id 放行，他人/未知因子拒绝。
- 全部 builtin 策略仍能通过校验（新规则不误伤合法代码）。
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from app.ai.validator import validate_strategy_code

_BASE = (
    "from __future__ import annotations\n"
    "import numpy as np\n"
    'META = {"id": "custom_x", "name": "x"}\n'
    "def _prev(a):\n"
    "    return a\n"
    "def compute(enriched, params):\n"
    "    return None\n"
)


class DunderNameTest(unittest.TestCase):
    def _rejected(self, extra: str) -> str:
        r = validate_strategy_code(_BASE + extra)
        self.assertFalse(r["valid"], extra)
        return r["error"]

    def test_builtins_subscript_exec_rejected(self) -> None:
        self.assertIn("__builtins__", self._rejected("__builtins__['exec']('x=1')\n"))

    def test_name_main_block_rejected_with_hint(self) -> None:
        err = self._rejected("if __name__ == '__main__':\n    pass\n")
        self.assertIn("自测块", err)
        self._rejected("__name__ = '__main__'\n")

    def test_dunder_definitions_rejected(self) -> None:
        self._rejected("def __init__():\n    pass\n")
        self._rejected("def f(__x):\n    return 1\n")

    def test_single_underscore_helper_allowed(self) -> None:
        self.assertTrue(validate_strategy_code(_BASE)["valid"])

    def test_injected_user_factor_key_allowed(self) -> None:
        ok = validate_strategy_code(
            _BASE + "def g(params):\n    return params['__user_factor_values__']\n"
        )
        self.assertTrue(ok["valid"], ok["error"])
        self._rejected("def g(params):\n    return params['__class__']\n")


class ImportAliasTest(unittest.TestCase):
    """导入名/别名绕过双下划线检查（review F5）。"""

    def test_dunder_import_names_rejected(self) -> None:
        for extra in (
            "from numpy import __builtins__ as b\n",
            "from numpy import __builtins__\n",
            "from numpy import _core\n",
            "from numpy import *\n",
            "import numpy as _np\n",
            "import numpy._core\n",
        ):
            with self.subTest(code=extra.strip()):
                self.assertFalse(validate_strategy_code(_BASE + extra)["valid"])

    def test_normal_imports_still_allowed(self) -> None:
        code = _BASE.replace(
            "import numpy as np\n",
            "import numpy as np\nimport polars as pl\nfrom numpy.lib.stride_tricks import sliding_window_view\n",
        )
        self.assertTrue(validate_strategy_code(code)["valid"])


class ForbiddenNameReferenceTest(unittest.TestCase):
    """危险名称的非调用引用 / 格式化字符串 / match 模式绕过（沙箱专项审查）。"""

    def test_indirect_references_rejected(self) -> None:
        for extra in (
            "@exec\ndef g():\n    pass\n",
            "def g(a=exec):\n    pass\n",
            "if (e := eval):\n    pass\n",
            "b = breakpoint\n",
            "s = '{0.__class__}'.format(1)\n",
            "def m(x):\n    match x:\n        case object(__class__=c):\n            return c\n",
        ):
            with self.subTest(code=extra.strip()):
                self.assertFalse(validate_strategy_code(_BASE + extra)["valid"])

    def test_ordinary_format_and_match_allowed(self) -> None:
        extra = (
            "s = '{:.2f}'.format(1.0) + '{0}'.format(2)\n"
            "def m(x):\n    match x:\n        case {'a': 1}:\n            return 1\n"
        )
        self.assertTrue(validate_strategy_code(_BASE + extra)["valid"])


class MetaImmutableTest(unittest.TestCase):
    def test_meta_mutation_rejected(self) -> None:
        for extra in (
            "META['params'] = []\n",
            "META.update({'a': 1})\n",
            'META = {"id": "custom_y", "name": "y"}\n',
            "def f():\n    global META\n",
        ):
            with self.subTest(code=extra.strip()):
                self.assertFalse(validate_strategy_code(_BASE + extra)["valid"])

    def test_reading_meta_allowed(self) -> None:
        self.assertTrue(validate_strategy_code(_BASE + "def g():\n    return META['id']\n")["valid"])


class ScoringUserFactorTest(unittest.TestCase):
    _CODE = _BASE.replace('"name": "x"}', '"name": "x", "scoring": {"uf_mom": 1.0}}')

    def _allowed(self, uid=None):
        base = frozenset({"close"})
        return base | {"uf_mom"} if uid == "u1" else base

    def test_own_active_factor_allowed_others_rejected(self) -> None:
        with mock.patch("app.ai.validator.allowed_scoring_fields", side_effect=self._allowed):
            self.assertTrue(validate_strategy_code(self._CODE, "u1")["valid"])
            r = validate_strategy_code(self._CODE, "u2")
            self.assertFalse(r["valid"])
            self.assertIn("uf_mom", r["error"])

    def test_no_user_rejects_user_factor(self) -> None:
        self.assertFalse(validate_strategy_code(self._CODE)["valid"])


class BuiltinRegressionTest(unittest.TestCase):
    def test_all_builtin_strategies_still_valid(self) -> None:
        import app.strategy.builtin as pkg

        for f in sorted(Path(pkg.__file__).parent.glob("*.py")):
            if f.name.startswith("_"):
                continue
            with self.subTest(file=f.name):
                r = validate_strategy_code(f.read_text(encoding="utf-8"))
                self.assertTrue(r["valid"], r["error"])


if __name__ == "__main__":
    unittest.main()
