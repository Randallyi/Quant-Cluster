# factors/ 模块 Phase 3 实现计划 —— gtja191 搬运

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搬运 Vibe-Trading `agent/src/factors/zoo/gtja191/` 全部 191 个 Alpha 因子，通过现有 `zoo_adapter.py` 自动注册到 `@factor` 注册机制。核心挑战：**约 25% 的 alpha 需要 `amount`（成交额）字段**，需设计自动推导方案。

**Architecture:** 与 Phase 1/2 一致——零修改原始因子逻辑，仅批量替换 import 路径。新增 `amount = close × volume` 自动推导逻辑，使 A 股导向的 gtja191 因子可迁移到任何有 OHLCV 数据的市场。

**Tech Stack:** Python 3.9, pandas, numpy, pytest. 无新增外部依赖。

---

## 背景调研结论

已对 Vibe-Trading gtja191 完成预扫描（基于已下载样本分析，模式一致）：

| 维度 | 结论 |
|------|------|
| 文件格式 | 与 alpha101 完全一致：`__alpha_meta__` + `compute(panel)` |
| 总文件数 | 191 个 `alpha_001.py` ~ `alpha_191.py` + `__init__.py` + `LICENSE.md` |
| import 来源 | 全部从 `src.factors.base` import 算子 |
| 算子依赖 | `rank`, `scale`, `ts_corr`, `ts_mean`, `ts_std`, `ts_max`, `ts_min`, `delta`, `safe_div`, `signed_power`, `ts_argmax`, `ts_argmin`, `ts_rank`, `ts_cov`, `decay_linear` —— **已全部在 `factors/core/ops.py` 中** |
| Sector 依赖 | **0 个** alpha 需要 sector 数据（比 alpha101 更干净） |
| `amount` 依赖 | **约 25%（~48 个）** alpha 需要 `amount`（成交额）字段 |
| `scale` 使用 | **约 15%（~29 个）** alpha 使用了 `scale` 算子 |
| `universe` | 标注为 `["equity_cn"]`，但因子逻辑纯价格/成交量驱动，可迁移 |

### `amount` 字段分析

`amount`（成交额）在 A 股数据中是独立字段，等于 `close × volume`。但在 IBKR/yfinance 的标准 OHLCV 输出中不包含 `amount`。

**数据需求分布（基于已分析样本）：**

| 数据组合 | 占比 | 说明 |
|---------|------|------|
| `['close']` | ~17% | 仅需收盘价 |
| `['close', 'high', 'low']` | ~7% | 经典 K 线 |
| `['close', 'volume']` | ~7% | 价量组合 |
| `['amount', 'close', 'high', 'low', 'open', 'volume']` | ~7% | 完整 A 股六字段 |
| `['amount', 'close', 'volume']` | ~5% | 金额 + 价量 |
| `['high', 'low']` | ~2% | 仅高低点 |
| 其他组合 | ~55% | 各种 OHLCV 子集组合 |

---

## 核心设计决策：`amount` 自动推导

### 问题

约 48 个 gtja191 alpha 在 `compute(panel)` 中直接访问 `panel["amount"]`：

```python
# gtja191 alpha 典型用法
amount = panel["amount"]  # KeyError if absent
```

标准 OHLCV 面板不包含 `amount`。

### 方案对比

| 方案 | 改动范围 | 优点 | 缺点 |
|------|---------|------|------|
| A. 修改 191 个 alpha 源码 | 191 个文件 | 最彻底 | 违反"零修改"原则，维护成本高 |
| B. Data Engineer 输出 amount | SOUL.md + 数据管道 | 数据层解决 | Agent 需记住额外字段，不通用 |
| C. `factor_tool.py` 自动推导 | 1 个文件 | CLI 路径覆盖 | 直接调用 `registry.compute()` 的路径不覆盖 |
| **D. `registry.py` 自动推导** | **1 个文件** | **所有路径覆盖** | **最小侵入，推荐** |

### 推荐方案 D：在 `registry.py` 中注入派生字段

在 `compute()` 调用 `meta.compute_fn()` 之前，自动注入可由已有字段推导的派生字段：

```python
# factors/registry.py

def _derive_fields(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Inject derived fields that alphas may expect but are not in raw OHLCV.

    Currently supports:
    - amount = close * volume (A-share turnover; used by gtja191)
    """
    derived = dict(data)
    if "amount" not in derived and "close" in derived and "volume" in derived:
        derived["amount"] = derived["close"] * derived["volume"]
    return derived
```

**安全性：**
- 仅在字段缺失时推导，不会覆盖已有数据
- 不影响 Phase 1/2 的因子（它们不使用 `amount`）
- 推导是惰性的、无副作用的

---

## 文件结构

### 新建/修改文件

| 文件 | 职责 | 状态 |
|------|------|------|
| `factors/zoo/gtja191/alpha_001.py` ~ `alpha_191.py` | **搬运** 191 个 GTJA Alpha 因子 | 新建 |
| `factors/zoo/gtja191/__init__.py` | 注册入口 | 新建 |
| `factors/zoo/gtja191/LICENSE.md` | 许可证（可选） | 新建 |
| `factors/registry.py` | **修改**：增加 `_derive_fields()`，在 `compute()` 中调用 | 修改 |
| `tests/factors/test_gtja191.py` | 抽样测试（~8 个代表性 alpha） | 新建 |
| `tests/factors/test_gtja191_amount.py` | amount 自动推导验证 | 新建 |

### 不变文件

| 文件 | 说明 |
|------|------|
| `factors/core/ops.py` | 算子层已覆盖 gtja191 全部需求（含 `scale`） |
| `factors/zoo_adapter.py` | 适配层无需改动 |
| `factors/bench_runner.py` | 评估引擎无需改动 |
| `tools/factor_tool.py` | CLI 无需改动（自动受益于 registry.py 的推导） |

---

## Task 1: 修改 `registry.py` — 增加 `amount` 自动推导

**目标:** 在 `compute()` 中注入 `_derive_fields()`，使 gtja191 的 `amount`-dependent alpha 无需额外数据即可运行。

### Step 1: 修改 `factors/registry.py`

```python
# factors/registry.py
# ... existing code ...


def _derive_fields(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Inject derived fields that alphas may expect but are not in raw OHLCV.

    Currently supports:
    - amount = close * volume (A-share turnover; used by gtja191)
    """
    derived = dict(data)
    if "amount" not in derived and "close" in derived and "volume" in derived:
        derived["amount"] = derived["close"] * derived["volume"]
    return derived


def compute(factor_name: str, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Lazy compute a single factor."""
    meta: FactorMeta | None = REGISTRY.get(factor_name)
    if meta is None:
        available = ", ".join(sorted(REGISTRY.keys()))
        raise ValueError(
            f"Factor '{factor_name}' not found in registry. "
            f"Available: {available}"
        )

    # Inject derived fields before checking missing inputs
    data = _derive_fields(data)

    missing = set(meta.inputs) - set(data.keys())
    if missing:
        raise ValueError(
            f"Missing required inputs for '{factor_name}': {sorted(missing)}. "
            f"Required: {meta.inputs}"
        )

    kwargs = {inp: data[inp] for inp in meta.inputs}
    return meta.compute_fn(**kwargs)
```

### Step 2: 运行现有测试确保无回归

```bash
python3 -m pytest tests/factors/test_registry.py tests/factors/test_factor_tool.py -v
```

Expected: 全部通过（Phase 1/2 测试不因 `amount` 推导而受影响）

### Step 3: 编写 amount 推导测试

```python
# tests/factors/test_gtja191_amount.py
import numpy as np
import pandas as pd
from factors.registry import compute


def test_amount_auto_derived():
    """amount should be auto-derived from close * volume when absent."""
    dates = pd.date_range("2023-01-01", periods=100, freq="D")
    close = pd.DataFrame({"SPY": 100 + np.cumsum(np.random.randn(100) * 0.5)}, index=dates)
    volume = pd.DataFrame({"SPY": np.random.randint(1_000_000, 10_000_000, 100)}, index=dates)
    
    # gtja191_001 needs volume, close, open — doesn't need amount
    # But let's verify amount is available for amount-dependent alphas
    # Use a simple check: compute should not raise KeyError for amount
    panel = {"close": close, "volume": volume}
    
    # Verify _derive_fields logic by checking a factor that needs amount
    # (We'll test with actual gtja191 alpha after Task 2)
    from factors.registry import _derive_fields
    derived = _derive_fields(panel)
    assert "amount" in derived
    pd.testing.assert_frame_equal(derived["amount"], close * volume)
```

---

## Task 2: 批量搬运 191 个 gtja191 文件

**目标:** 将 Vibe-Trading `gtja191/` 目录下全部 191 个 `.py` 文件下载到本地，并批量替换 import 路径。

### Step 1: 编写并执行批量搬运脚本

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"

mkdir -p factors/zoo/gtja191

# 下载全部 191 个文件（串行+sleep，避免 GitHub 429）
for i in $(seq -w 1 191); do
    curl -sL --max-time 10 "https://raw.githubusercontent.com/HKUDS/Vibe-Trading/main/agent/src/factors/zoo/gtja191/alpha_${i}.py" \
        > "factors/zoo/gtja191/alpha_${i}.py"
    sleep 0.5
done

# 验证下载完整性
valid=$(grep -l 'def compute' factors/zoo/gtja191/alpha_*.py | wc -l)
echo "Valid files: $valid / 191"

# 如果有缺失，重试
if [ "$valid" -lt 191 ]; then
    for i in $(seq -w 1 191); do
        f="factors/zoo/gtja191/alpha_${i}.py"
        if [ ! -f "$f" ] || ! grep -q 'def compute' "$f"; then
            curl -sL --max-time 15 "https://raw.githubusercontent.com/HKUDS/Vibe-Trading/main/agent/src/factors/zoo/gtja191/alpha_${i}.py" > "$f"
            sleep 1
        fi
    done
fi
```

### Step 2: 批量替换 import 路径

```bash
find factors/zoo/gtja191 -name "alpha_*.py" -exec \
    sed -i '' 's/from src\.factors\.base import/from factors.core.ops import/g' {} \;

grep -l "from src.factors.base import" factors/zoo/gtja191/*.py || echo "All imports replaced successfully"
```

### Step 3: 编写 `gtja191/__init__.py`

```python
"""GTJA191 factor zoo — auto-registers all alphas on import."""
```

### Step 4: 搬运 LICENSE.md（可选）

```bash
curl -sL "https://raw.githubusercontent.com/HKUDS/Vibe-Trading/main/agent/src/factors/zoo/gtja191/LICENSE.md" \
    > factors/zoo/gtja191/LICENSE.md
```

### Step 5: 验证注册

```python
from factors.registry import list_factors
gtja = [f for f in list_factors() if f["category"] == "gtja191"]
assert len(gtja) == 191, f"Expected 191 gtja191 factors, got {len(gtja)}"
print(f"Registered {len(gtja)} gtja191 factors")
```

---

## Task 3: 抽样测试（~8 个代表性 alpha）

**目标:** 抽样测试覆盖不同数据需求、amount 依赖、以及特殊算子组合。

### 抽样清单

| 测试函数 | Alpha | 数据需求 | 说明 |
|---------|-------|---------|------|
| `test_gtja001` | gtja191_001 | volume, close, open | 经典价量相关性 |
| `test_gtja050` | gtja191_050 | high, low | 仅高低点 |
| `test_gtja091` | gtja191_091 | close, volume | amount 推导验证 |
| `test_gtja100` | gtja191_100 | amount, close, volume | 直接依赖 amount |
| `test_gtja150` | gtja191_150 | close, high, low, open, volume | 完整 OHLCV |
| `test_gtja191` | gtja191_191 | open, high, low, close, volume | 最后一个 alpha |

> **注意**：抽样前需查看实际 `columns_required`，以上清单基于预扫描推断，执行时可能需要调整。

### 测试文件模板

```python
# tests/factors/test_gtja191.py
import numpy as np
import pandas as pd
import pytest

from factors.registry import compute


def _make_panel(fields):
    """Helper: create synthetic OHLCV+ panel."""
    dates = pd.date_range("2023-01-01", periods=300, freq="D")
    symbols = ["SPY", "QQQ"]
    np.random.seed(42)
    panel = {}
    for field in fields:
        if field in ("open", "high", "low", "close"):
            panel[field] = pd.DataFrame(
                {sym: 100 + np.cumsum(np.random.randn(300) * 0.5) + np.random.randn(300) * 0.1
                 for sym in symbols},
                index=dates
            )
        elif field == "volume":
            panel[field] = pd.DataFrame(
                {sym: np.random.randint(1_000_000, 10_000_000, 300) for sym in symbols},
                index=dates
            )
        elif field == "vwap":
            panel[field] = pd.DataFrame(
                {sym: 100 + np.cumsum(np.random.randn(300) * 0.3) for sym in symbols},
                index=dates
            )
        else:
            raise ValueError(f"Unknown field: {field}")
    return panel


class TestGtja191:
    def test_gtja001(self):
        panel = _make_panel(["volume", "close", "open"])
        result = compute("gtja191_001", panel)
        assert isinstance(result, pd.DataFrame)
        assert result.shape[0] == 300

    def test_gtja050(self):
        panel = _make_panel(["high", "low"])
        result = compute("gtja191_050", panel)
        assert isinstance(result, pd.DataFrame)

    def test_gtja091(self):
        """Alpha that needs amount — should work via auto-derivation."""
        panel = _make_panel(["close", "volume"])
        result = compute("gtja191_091", panel)
        assert isinstance(result, pd.DataFrame)

    def test_gtja100(self):
        """Alpha that explicitly needs amount — should work via auto-derivation."""
        panel = _make_panel(["close", "volume"])
        result = compute("gtja191_100", panel)
        assert isinstance(result, pd.DataFrame)

    def test_gtja150(self):
        panel = _make_panel(["close", "high", "low", "open", "volume"])
        result = compute("gtja191_150", panel)
        assert isinstance(result, pd.DataFrame)

    def test_gtja191(self):
        panel = _make_panel(["open", "high", "low", "close", "volume"])
        result = compute("gtja191_191", panel)
        assert isinstance(result, pd.DataFrame)
```

### 运行测试

```bash
python3 -m pytest tests/factors/test_gtja191.py tests/factors/test_gtja191_amount.py -v
```

Expected: 全部通过

---

## Task 4: 全量 dry-run 验证

**目标:** 验证全部 191 个 gtja191 alpha 都能被正确评估，包括 amount-dependent 的 alpha。

### 验证脚本

```bash
# 1. 确认注册数量
python3 -c "
from factors.registry import list_factors
gtja = [f for f in list_factors() if f['category'] == 'gtja191']
print(f'gtja191 registered: {len(gtja)}')
assert len(gtja) == 191
"

# 2. 生成合成数据并 bench_category
python3 << 'PYEOF'
import numpy as np
import pandas as pd
import subprocess, sys, tempfile, json
from pathlib import Path

# Build synthetic panel with OHLCV (amount will be auto-derived)
fields = ["open", "high", "low", "close", "volume"]
dates = pd.date_range("2023-01-01", periods=300, freq="D")
symbols = ["SPY", "QQQ", "AAPL"]
np.random.seed(42)

data = {}
for sym in symbols:
    base = 100 + np.cumsum(np.random.randn(300) * 0.5)
    data[(sym, "open")] = base + np.random.randn(300) * 0.1
    data[(sym, "high")] = base + abs(np.random.randn(300)) * 0.2
    data[(sym, "low")] = base - abs(np.random.randn(300)) * 0.2
    data[(sym, "close")] = base
    data[(sym, "volume")] = np.random.randint(1_000_000, 10_000_000, 300)

df = pd.DataFrame(data, index=dates)
df.columns = pd.MultiIndex.from_tuples(df.columns)

with tempfile.TemporaryDirectory() as tmp:
    panel_path = Path(tmp) / "panel.parquet"
    df.to_parquet(panel_path)
    out_dir = Path(tmp) / "bench"
    
    result = subprocess.run([
        sys.executable, "tools/factor_tool.py",
        "--action", "bench_category",
        "--category", "gtja191",
        "--data", str(panel_path),
        "--out-dir", str(out_dir),
    ], capture_output=True, text=True)
    
    print(result.stdout)
    if result.returncode != 0:
        print("STDERR:", result.stderr)
        sys.exit(1)
    
    summary_path = out_dir / "bench_summary_gtja191.json"
    with open(summary_path) as f:
        summary = json.load(f)
    
    print(f"\nBenched {len(summary)} gtja191 factors")
    success = sum(1 for v in summary.values() if "error_type" not in v)
    failed = sum(1 for v in summary.values() if "error_type" in v)
    print(f"  Success: {success}, Failed: {failed}")
    assert success == 191, f"Expected all 191 to succeed, got {success}"
    print("ALL 191 GTJA ALPHA PASSED")
PYEOF
```

**期望结果:**
- **全部 191 个 alpha 成功 bench**
- amount-dependent alpha 通过 `registry.py` 的 `_derive_fields()` 自动推导 `amount = close * volume`，无需失败
- `bench_summary_gtja191.json` 成功生成

---

## Task 5: 集成验证

### 验证清单

- [ ] `factor_tool.py --action list` 返回 298 个因子（6 academic + 101 alpha101 + 191 gtja191）
- [ ] `factor_tool.py --action list --category gtja191` 返回 191 个因子
- [ ] `factor_tool.py --action bench --factor gtja191_001` 成功计算 IC/IR
- [ ] `factor_tool.py --action signal --factor gtja191_001` 输出 signal.parquet
- [ ] `factor_tool.py --action bench_category --category gtja191` 处理全部 191 个因子
- [ ] 运行 `scripts/verify_factor_backtest.sh` 仍通过（Phase 1/2 未破坏）
- [ ] `tests/factors/` 全部测试通过（Phase 1 + 2 + 3）

---

## Task 6: Commit

```bash
git add factors/zoo/gtja191/ tests/factors/test_gtja191.py tests/factors/test_gtja191_amount.py factors/registry.py
git commit -m "feat(factors): port Vibe-Trading gtja191 (191 alphas) + auto-derive amount

- Bulk import 191 gtja191 alpha files from Vibe-Trading
- Import path: src.factors.base -> factors.core.ops
- auto_register_zoo picks up gtja191/ automatically
- registry.py: add _derive_fields() to auto-inject amount = close * volume
  - Makes A-share oriented gtja191 alphas portable to any OHLCV market
  - Zero modification to original alpha logic
- Sample tests for 6 representative alphas (001, 050, 091, 100, 150, 191)
- bench_category gtja191 verifies all 191 factors evaluate successfully"
```

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 批量下载 191 个文件时网络超时/429 | 中 | 搬运不完整 | 串行下载+sleep(0.5s)；下载后计数验证；缺失文件重试 |
| 某些 alpha 使用 ops.py 中未实现的算子 | 低 | 运行时错误 | 抽样测试覆盖多种算子组合；全量 dry-run 暴露问题 |
| amount 推导精度问题 | 低 | 因子值偏差 | amount = close * volume 是 A 股标准定义；推导逻辑仅在缺失时注入，不会覆盖真实数据 |
| 191 个文件触发 Git pre-commit 性能问题 | 低 | commit 变慢 | 一次性大量文件提交；pre-commit 只运行 validate.py（轻量） |

---

## 工作量估算

| 任务 | 预估时间 |
|------|---------|
| Task 1: 修改 registry.py + amount 推导测试 | 15 min |
| Task 2: 批量搬运脚本 + 执行 | 20 min |
| Task 3: 抽样测试编写 + 运行 | 20 min |
| Task 4: 全量 dry-run 验证 | 20 min |
| Task 5: 集成验证 | 10 min |
| Task 6: Commit | 5 min |
| **总计** | **~90 min** |
