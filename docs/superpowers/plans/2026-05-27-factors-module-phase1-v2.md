# factors/ 模块 Phase 1 v2 实现计划（搬运 Vibe-Trading）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搬运 Vibe-Trading `agent/src/factors/base.py` 算子 + `zoo/academic/` 6 个因子文件，通过 `zoo_adapter.py` 适配到 `@factor` 注册机制，封装为 Agent CLI tool。

**Architecture:** 搬运 Vibe-Trading 的算子层和因子实现，通过轻量适配层（`zoo_adapter.py`）桥接到 `@factor` 装饰器注册机制。零修改原始因子逻辑，仅批量替换 import 路径。

**Tech Stack:** Python 3.9, pandas, numpy, pytest. 无新增外部依赖。

---

## 文件结构

### 新建文件

| 文件 | 职责 |
|------|------|
| `factors/__init__.py` | 包入口 |
| `factors/core/__init__.py` | core 子包入口 |
| `factors/core/meta.py` | `@factor` 装饰器 + `FactorMeta` |
| `factors/core/ops.py` | **搬运** Vibe-Trading `base.py` 全部算子 |
| `factors/zoo/__init__.py` | zoo 根入口 |
| `factors/zoo/academic/__init__.py` | 注册入口：遍历目录，@factor 包装 |
| `factors/zoo/academic/carhart_mom.py` | **搬运** Vibe-Trading |
| `factors/zoo/academic/smb.py` | **搬运** Vibe-Trading |
| `factors/zoo/academic/hml.py` | **搬运** Vibe-Trading |
| `factors/zoo/academic/rmw.py` | **搬运** Vibe-Trading |
| `factors/zoo/academic/cma.py` | **搬运** Vibe-Trading |
| `factors/zoo/academic/mkt_rf.py` | **搬运** Vibe-Trading |
| `factors/zoo/alpha101/__init__.py` | 占位（Phase 2） |
| `factors/zoo/gtja191/__init__.py` | 占位（Phase 3） |
| `factors/zoo_adapter.py` | 适配层：读取 `__alpha_meta__`，@factor 包装 |
| `factors/registry.py` | 全局注册表 |
| `factors/bench_runner.py` | IC/IR + alive/reversed/dead 分类 |
| `tools/factor_tool.py` | Agent CLI 入口 |
| `tests/factors/__init__.py` | 测试包入口 |
| `tests/factors/test_meta.py` | @factor 装饰器测试 |
| `tests/factors/test_ops.py` | 算子测试 |
| `tests/factors/test_academic.py` | academic 因子测试 |
| `tests/factors/test_registry.py` | 注册表测试 |
| `tests/factors/test_bench_runner.py` | bench_runner 测试 |
| `tests/factors/test_factor_tool.py` | CLI 集成测试 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `agent_configs/hypothesis/SOUL.md` | 新增「因子族选择」 |
| `agent_configs/data_engineer/SOUL.md` | 新增「标准化面板输出」 |
| `agent_configs/quant_analyst/SOUL.md` | 新增「因子库使用规范」 |

---

## Task 1: `factors/core/meta.py` — @factor 装饰器 + FactorMeta

**Files:**
- Create: `factors/core/meta.py`
- Test: `tests/factors/test_meta.py`

与 v1 相同，保留 `@factor` 装饰器架构。

- [ ] **Step 1: Write the failing test**

```python
# tests/factors/test_meta.py
import pytest
from factors.core.meta import factor, FactorMeta, REGISTRY, unregister


@pytest.fixture(autouse=True)
def clean_registry():
    keys_before = set(REGISTRY.keys())
    yield
    for key in set(REGISTRY.keys()) - keys_before:
        unregister(key)


def test_factor_decorator_registers_meta():
    @factor(
        name="test.mom",
        category="test",
        inputs=["close"],
        outputs=["mom"],
        description="Test momentum"
    )
    def test_mom(close):
        return close.pct_change(20)

    assert "test.mom" in REGISTRY
    meta = REGISTRY["test.mom"]
    assert isinstance(meta, FactorMeta)
    assert meta.name == "test.mom"
    assert meta.inputs == ["close"]
    assert meta.outputs == ["mom"]


def test_factor_decorator_preserves_function():
    @factor(name="test.smb", category="test", inputs=["close"], outputs=["smb"])
    def test_smb(close):
        return close

    import pandas as pd
    df = pd.DataFrame({"A": [1.0, 2.0]})
    result = test_smb(df)
    assert result is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/yihaoyang/VScode workspace/quant-cluster" && python3 -m pytest tests/factors/test_meta.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'factors'`

- [ ] **Step 3: Write minimal implementation**

```python
# factors/core/meta.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


__all__ = ["FactorMeta", "factor", "REGISTRY", "unregister"]


@dataclass
class FactorMeta:
    """Metadata for a single factor."""
    name: str
    category: str
    inputs: list[str]
    outputs: list[str]
    description: str
    compute_fn: Callable


REGISTRY: dict[str, FactorMeta] = {}


def factor(
    name: str,
    category: str,
    inputs: list[str],
    outputs: list[str],
    description: str = "",
) -> Callable:
    """Decorator that registers a factor function in the global REGISTRY."""
    def decorator(fn: Callable) -> Callable:
        meta = FactorMeta(
            name=name, category=category, inputs=inputs,
            outputs=outputs, description=description, compute_fn=fn,
        )
        REGISTRY[name] = meta
        return fn
    return decorator


def unregister(name: str) -> None:
    """Remove a factor from the registry."""
    REGISTRY.pop(name, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/factors/test_meta.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/factors/__init__.py tests/factors/test_meta.py factors/__init__.py factors/core/__init__.py factors/core/meta.py
git commit -m "feat(factors): add @factor decorator and FactorMeta"
```

---

## Task 2: `factors/core/ops.py` — 搬运 Vibe-Trading base.py 算子

**Files:**
- Create: `factors/core/ops.py`
- Test: `tests/factors/test_ops.py`

**说明：** 从 Vibe-Trading `agent/src/factors/base.py` 搬运全部算子。alpha101/gtja191 重度依赖这些算子。

搬运清单：rank, scale, ts_rank, ts_corr, ts_cov, ts_mean, ts_std, ts_max, ts_min, ts_argmax, ts_argmin, delta, safe_div, signed_power, decay_linear。

搬运时仅做以下修改：
- 移除 `Market` enum、`Alpha` dataclass、`AlphaCompute` Protocol
- 保留所有算子函数的实现不变
- 添加 `__all__`

- [ ] **Step 1: 搬运 base.py 算子**

下载 Vibe-Trading base.py：
```bash
curl -sL "https://raw.githubusercontent.com/HKUDS/Vibe-Trading/main/agent/src/factors/base.py" > /tmp/vt_base.py
```

创建 `factors/core/ops.py`，内容基于 Vibe-Trading base.py：
- 保留文档字符串中的面板数据约定
- 保留所有算子实现
- 移除 registry 相关类

- [ ] **Step 2: 写测试**

```python
# tests/factors/test_ops.py
import numpy as np
import pandas as pd
import pytest

from factors.core.ops import rank, scale, ts_rank, ts_corr, ts_mean, ts_std, delta, safe_div, signed_power, decay_linear


def test_rank_basic():
    df = pd.DataFrame({"A": [1.0, 3.0], "B": [3.0, 1.0]})
    result = rank(df)
    # Row 0: A=1/4, B=3/4
    assert result.iloc[0, 0] == pytest.approx(0.25)
    assert result.iloc[0, 1] == pytest.approx(0.75)


def test_scale_basic():
    df = pd.DataFrame({"A": [1.0, -1.0], "B": [1.0, -1.0]})
    result = scale(df)
    # Row 0: abs_sum=2, scale to 1 -> A=0.5, B=0.5
    assert result.iloc[0, 0] == pytest.approx(0.5)


def test_ts_rank_basic():
    df = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0]})
    result = ts_rank(df, 3)
    # Row 2: [1,2,3] -> last=3, rank=3/3=1.0
    assert result.iloc[2, 0] == pytest.approx(1.0)


def test_ts_corr_basic():
    x = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0, 5.0]})
    y = pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0, 5.0]})
    result = ts_corr(x, y, 3)
    # Row 4: perfect correlation -> 1.0
    assert result.iloc[4, 0] == pytest.approx(1.0)


def test_delta_basic():
    df = pd.DataFrame({"A": [1.0, 3.0, 6.0]})
    result = delta(df, 1)
    assert result.iloc[1, 0] == pytest.approx(2.0)
    assert result.iloc[2, 0] == pytest.approx(3.0)


def test_safe_div_basic():
    a = pd.DataFrame({"A": [1.0, 2.0]})
    b = pd.DataFrame({"A": [2.0, 0.0]})
    result = safe_div(a, b)
    assert result.iloc[0, 0] == pytest.approx(0.5)
    assert np.isnan(result.iloc[1, 0])


def test_signed_power_basic():
    df = pd.DataFrame({"A": [-2.0, 3.0]})
    result = signed_power(df, 2.0)
    assert result.iloc[0, 0] == pytest.approx(-4.0)
    assert result.iloc[1, 0] == pytest.approx(9.0)
```

- [ ] **Step 3: Run test**

Run: `python3 -m pytest tests/factors/test_ops.py -v`

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/factors/test_ops.py factors/core/ops.py
git commit -m "feat(factors): port Vibe-Trading base.py operators to core/ops.py"
```

---

## Task 3: 搬运 `factors/zoo/academic/` 因子文件

**Files:**
- Create: `factors/zoo/__init__.py`
- Create: `factors/zoo/academic/__init__.py`
- Create: `factors/zoo/academic/carhart_mom.py` (搬运)
- Create: `factors/zoo/academic/smb.py` (搬运)
- Create: `factors/zoo/academic/hml.py` (搬运)
- Create: `factors/zoo/academic/rmw.py` (搬运)
- Create: `factors/zoo/academic/cma.py` (搬运)
- Create: `factors/zoo/academic/mkt_rf.py` (搬运)
- Test: `tests/factors/test_academic.py`

**搬运步骤（每个文件相同）：**
1. `curl` 下载 Vibe-Trading 原始文件
2. 仅替换 import：`from src.factors.base import` → `from factors.core.ops import`
3. 其他代码**一字不改**

- [ ] **Step 1: 下载并搬运 6 个 academic 因子**

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"
mkdir -p factors/zoo/academic

for f in carhart_mom smb hml rmw cma mkt_rf; do
    curl -sL "https://raw.githubusercontent.com/HKUDS/Vibe-Trading/main/agent/src/factors/zoo/academic/${f}.py" > "factors/zoo/academic/${f}.py"
    # 替换 import 路径
    sed -i '' 's/from src\.factors\.base import/from factors.core.ops import/g' "factors/zoo/academic/${f}.py"
done
```

- [ ] **Step 2: 创建 zoo 注册入口**

```python
# factors/zoo/__init__.py
"""Vibe-Trading factor zoo root."""
```

```python
# factors/zoo/academic/__init__.py
"""Academic factor zoo — auto-registers all alphas on import."""
```

- [ ] **Step 3: 写测试**

```python
# tests/factors/test_academic.py
import numpy as np
import pandas as pd
import pytest

# Import triggers zoo_adapter registration
from factors.zoo.academic import carhart_mom, smb, hml, rmw, cma, mkt_rf


def test_carhart_mom_compute():
    dates = pd.date_range("2023-01-01", periods=300, freq="D")
    close = pd.DataFrame({"SPY": 100 + np.arange(300) * 0.1}, index=dates)
    panel = {"close": close}
    result = carhart_mom.compute(panel)
    assert isinstance(result, pd.DataFrame)
    assert result.shape == (300, 1)


def test_carhart_mom_meta():
    assert carhart_mom.__alpha_meta__['id'] == 'academic_carhart_mom'
    assert 'close' in carhart_mom.__alpha_meta__['columns_required']
```

- [ ] **Step 4: Run test**

Run: `python3 -m pytest tests/factors/test_academic.py -v`

Expected: PASS（可能需要修复 Python 3.9 兼容性问题）

- [ ] **Step 5: Commit**

```bash
git add factors/zoo/ tests/factors/test_academic.py
git commit -m "feat(factors): port Vibe-Trading academic zoo (carhart_mom, smb, hml, rmw, cma, mkt_rf)"
```

---

## Task 4: `factors/zoo_adapter.py` — 适配层

**Files:**
- Create: `factors/zoo_adapter.py`
- Test: `tests/factors/test_registry.py`

**说明：** 扫描 `factors/zoo/` 目录，读取每个 `.py` 文件的 `__alpha_meta__`，用 `@factor` 包装 `compute`，注册到全局 REGISTRY。

- [ ] **Step 1: Write the failing test**

```python
# tests/factors/test_registry.py
import pandas as pd
import pytest

from factors.registry import list_factors, compute


class TestListFactors:
    def test_list_factors_has_academic(self):
        factors_list = list_factors()
        names = [f["name"] for f in factors_list]
        assert "academic_carhart_mom" in names

    def test_list_factors_filter_by_category(self):
        factors_list = list_factors(category="academic")
        assert all(f["category"] == "academic" for f in factors_list)


class TestCompute:
    def test_compute_carhart_mom(self):
        dates = pd.date_range("2023-01-01", periods=300, freq="D")
        close = pd.DataFrame({"SPY": 100.0 + np.arange(300) * 0.1}, index=dates)
        result = compute("academic_carhart_mom", {"close": close})
        assert isinstance(result, pd.DataFrame)

    def test_compute_unknown_factor(self):
        with pytest.raises(ValueError, match="not found"):
            compute("unknown.factor", {"close": pd.DataFrame()})
```

- [ ] **Step 2: Write implementation**

```python
# factors/zoo_adapter.py
"""Adapt Vibe-Trading zoo modules to @factor registry.

Scans factors/zoo/ directories, imports each alpha module,
reads __alpha_meta__, and registers a @factor-wrapped compute.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

import pandas as pd

from factors.core.meta import FactorMeta, REGISTRY

logger = logging.getLogger(__name__)


def _register_zoo_module(module_name: str, category: str) -> None:
    """Import a zoo module and register its compute function."""
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:
        logger.warning("Failed to import %s: %s", module_name, exc)
        return

    if not hasattr(mod, '__alpha_meta__') or not hasattr(mod, 'compute'):
        return

    meta = mod.__alpha_meta__
    compute_fn = mod.compute
    alpha_id = meta['id']
    columns_required = meta.get('columns_required', [])
    nickname = meta.get('nickname', alpha_id)

    # Wrap compute — data dict format is identical to Vibe-Trading panel dict
    def _wrapped_compute(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        return compute_fn(data)

    REGISTRY[alpha_id] = FactorMeta(
        name=alpha_id,
        category=category,
        inputs=columns_required,
        outputs=[alpha_id],
        description=nickname,
        compute_fn=_wrapped_compute,
    )


def register_all_zoos() -> None:
    """Scan and register all zoo modules."""
    zoo_root = Path(__file__).parent / 'zoo'
    if not zoo_root.exists():
        return

    for zoo_dir in sorted(zoo_root.iterdir()):
        if not zoo_dir.is_dir() or zoo_dir.name.startswith('_'):
            continue
        category = zoo_dir.name
        init_file = zoo_dir / '__init__.py'
        if not init_file.exists():
            continue

        for py_file in sorted(zoo_dir.glob('*.py')):
            if py_file.name.startswith('_'):
                continue
            module_name = f"factors.zoo.{category}.{py_file.stem}"
            _register_zoo_module(module_name, category)
```

```python
# factors/registry.py
"""Global factor registry with lazy compute dispatch."""

from __future__ import annotations

import pandas as pd

from factors.core.meta import REGISTRY, FactorMeta

# Auto-register all zoo modules on import
from factors.zoo_adapter import register_all_zoos
register_all_zoos()


def list_factors(category: str = "") -> list[dict]:
    """Return metadata for all registered factors."""
    result = []
    for name, meta in REGISTRY.items():
        if category and meta.category != category:
            continue
        result.append({
            "name": meta.name,
            "category": meta.category,
            "inputs": meta.inputs,
            "outputs": meta.outputs,
            "description": meta.description,
        })
    return result


def compute(factor_name: str, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Lazy compute a single factor."""
    meta: FactorMeta | None = REGISTRY.get(factor_name)
    if meta is None:
        available = ", ".join(sorted(REGISTRY.keys()))
        raise ValueError(
            f"Factor '{factor_name}' not found in registry. "
            f"Available: {available}"
        )

    missing = set(meta.inputs) - set(data.keys())
    if missing:
        raise ValueError(
            f"Missing required inputs for '{factor_name}': {sorted(missing)}. "
            f"Required: {meta.inputs}"
        )

    kwargs = {inp: data[inp] for inp in meta.inputs}
    return meta.compute_fn(**kwargs)
```

```python
# factors/__init__.py
"""Quant Cluster factor library."""

from factors.registry import list_factors, compute  # noqa: F401
```

- [ ] **Step 3: Run test**

Run: `python3 -m pytest tests/factors/test_registry.py -v`

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add factors/zoo_adapter.py factors/registry.py factors/__init__.py tests/factors/test_registry.py
git commit -m "feat(factors): add zoo_adapter + registry with auto-scan and @factor wrapping"
```

---

## Task 5: `factors/bench_runner.py` — IC/IR + alive/reversed/dead

与 v1 plan 相同。搬运 v1 的实现。

- [ ] 创建 `factors/bench_runner.py` 和 `tests/factors/test_bench_runner.py`
- [ ] 运行测试：全部通过
- [ ] Commit

---

## Task 6: `tools/factor_tool.py` — Agent CLI 入口

与 v1 plan 相同，但 factor 名称使用 Vibe-Trading 的 `id`（如 `academic_carhart_mom`）。

- [ ] 创建 `tools/factor_tool.py` 和 `tests/factors/test_factor_tool.py`
- [ ] 运行测试：全部通过
- [ ] Commit

---

## Task 7: Agent SOUL.md 更新

与 v1 plan 相同，但 factor 名称示例更新为 Vibe-Trading 的 id：
- `academic_carhart_mom` 替代 `academic.mom_12_2`
- `alpha101_001` 替代 `alpha101.alpha001`

---

## Task 8: 集成验证

- [ ] 运行全部 factors 测试
- [ ] 创建并运行 `scripts/verify_factor_backtest.sh`
- [ ] 验证 `academic_carhart_mom` 可 bench、可生成信号
- [ ] Commit
