# factors/ 模块 Phase 2 实现计划 —— alpha101 搬运

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搬运 Vibe-Trading `agent/src/factors/zoo/alpha101/` 全部 101 个 Alpha 因子，通过现有 `zoo_adapter.py` 自动注册到 `@factor` 注册机制。

**Architecture:** 与 Phase 1 完全一致——零修改原始因子逻辑，仅批量替换 import 路径。`zoo_adapter.py` 和 `registry.py` 无需改动。

**Tech Stack:** Python 3.9, pandas, numpy, pytest. 无新增外部依赖。

---

## 背景调研结论

已对 Vibe-Trading alpha101 全量 101 个文件完成预扫描：

| 维度 | 结论 |
|------|------|
| 文件格式 | 与 academic 完全一致：`__alpha_meta__` + `compute(panel)` |
| 总文件数 | 101 个 `alpha_001.py` ~ `alpha_101.py` + `__init__.py` + `LICENSE.md` |
| import 来源 | 全部从 `src.factors.base` import 算子 |
| 算子依赖 | `rank`, `scale`, `ts_rank`, `ts_corr`, `ts_cov`, `ts_mean`, `ts_std`, `ts_max`, `ts_min`, `ts_argmax`, `ts_argmin`, `delta`, `decay_linear`, `signed_power`, `safe_div` —— **已全部在 `factors/core/ops.py` 中** |
| Sector 依赖 | **19 个 alpha 需要 sector 数据**（`requires_sector: True`）：048, 056, 058, 059, 063, 067, 069, 070, 076, 079, 080, 082, 087, 089, 090, 091, 093, 097, 100 |
| 数据需求 | 最常用：`['close', 'volume', 'vwap']` (14), `['close']` (11), `['close', 'volume']` (10), 完整 OHLCV (8) |
| `__init__.py` | Vibe-Trading 源文件为空（或极简），需自行编写注册入口 |

---

## 文件结构

### 新建/修改文件

| 文件 | 职责 |
|------|------|
| `factors/zoo/alpha101/alpha_001.py` ~ `alpha_101.py` | **搬运** 101 个 Alpha 因子（仅改 import 路径） |
| `factors/zoo/alpha101/__init__.py` | 注册入口：遍历目录，@factor 包装 |
| `tests/factors/test_alpha101.py` | 抽样测试（~10 个代表性 alpha） |
| `tests/factors/test_alpha101_sector.py` | Sector-dependent alpha 跳过/错误测试 |
| `scripts/bulk_import_alpha101.sh` | 一次性批量下载 + import 替换脚本 |

### 不变文件（Phase 1 已就绪）

| 文件 | 说明 |
|------|------|
| `factors/core/ops.py` | 算子层已覆盖 alpha101 全部需求 |
| `factors/zoo_adapter.py` | 适配层无需改动 |
| `factors/registry.py` | 自动扫描 `zoo/` 所有子目录，无需改动 |
| `factors/bench_runner.py` | 评估引擎无需改动 |
| `tools/factor_tool.py` | CLI 无需改动 |

---

## Task 1: 批量搬运 101 个 alpha 文件

**目标:** 将 Vibe-Trading `alpha101/` 目录下全部 101 个 `.py` 文件下载到本地，并批量替换 import 路径。

### Step 1: 编写并执行批量搬运脚本

```bash
cd "/Users/yihaoyang/VScode workspace/quant-cluster"

mkdir -p factors/zoo/alpha101

# 下载全部 101 个文件
for i in $(seq -w 1 101); do
    curl -sL "https://raw.githubusercontent.com/HKUDS/Vibe-Trading/main/agent/src/factors/zoo/alpha101/alpha_${i}.py" \
        > "factors/zoo/alpha101/alpha_${i}.py"
done

# 批量替换 import 路径
find factors/zoo/alpha101 -name "alpha_*.py" -exec \
    sed -i '' 's/from src\.factors\.base import/from factors.core.ops import/g' {} \;

# 验证替换成功
grep -l "from src.factors.base import" factors/zoo/alpha101/*.py || echo "All imports replaced successfully"
```

### Step 2: 搬运 LICENSE.md（可选，但建议保留）

```bash
curl -sL "https://raw.githubusercontent.com/HKUDS/Vibe-Trading/main/agent/src/factors/zoo/alpha101/LICENSE.md" \
    > factors/zoo/alpha101/LICENSE.md
```

### Step 3: 编写 `alpha101/__init__.py`

与 `academic/__init__.py` 相同（空文件即可，`registry.py` 的 `auto_register_zoo` 会自动扫描）：

```python
"""Alpha101 factor zoo — auto-registers all alphas on import."""
```

> **注意**：`registry.py` 的 `auto_register_zoo` 会递归扫描 `factors/zoo/` 下所有子目录。alpha101 目录一旦存在 `.py` 文件，就会被自动注册。**无需修改 `registry.py`**。

### Step 4: 验证注册

```python
from factors.registry import list_factors
alphas = [f for f in list_factors() if f["category"] == "alpha101"]
assert len(alphas) == 101, f"Expected 101 alpha101 factors, got {len(alphas)}"
print(f"Registered {len(alphas)} alpha101 factors")
```

---

## Task 2: 抽样测试（~10 个代表性 alpha）

**目标:** 不测试全部 101 个（维护成本过高），抽样测试覆盖不同数据需求和算子组合。

### 抽样清单

| 测试函数 | Alpha | 数据需求 | 覆盖算子 |
|---------|-------|---------|---------|
| `test_alpha001` | alpha101_001 | close | `rank`, `ts_argmax`, `signed_power`, `ts_std`, `delta` |
| `test_alpha002` | alpha101_002 | open, close, volume | `ts_corr`, `rank`, `delta` |
| `test_alpha003` | alpha101_003 | open, volume, close | `ts_corr`, `rank` |
| `test_alpha010` | alpha101_010 | close, volume, vwap | `rank`, `ts_corr`, `ts_max` |
| `test_alpha050` | alpha101_050 | volume, vwap, close | `ts_max`, `rank`, `ts_corr` |
| `test_alpha101` | alpha101_101 | close | `rank`, `ts_mean`, `delta`, `safe_div` |

### 测试文件模板

```python
# tests/factors/test_alpha101.py
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


class TestAlpha101:
    def test_alpha001(self):
        panel = _make_panel(["close"])
        result = compute("alpha101_001", panel)
        assert isinstance(result, pd.DataFrame)
        assert result.shape[0] == 300

    def test_alpha002(self):
        panel = _make_panel(["open", "close", "volume"])
        result = compute("alpha101_002", panel)
        assert isinstance(result, pd.DataFrame)

    def test_alpha003(self):
        panel = _make_panel(["open", "volume", "close"])
        result = compute("alpha101_003", panel)
        assert isinstance(result, pd.DataFrame)

    def test_alpha010(self):
        panel = _make_panel(["close", "volume", "vwap"])
        result = compute("alpha101_010", panel)
        assert isinstance(result, pd.DataFrame)

    def test_alpha050(self):
        panel = _make_panel(["volume", "vwap", "close"])
        result = compute("alpha101_050", panel)
        assert isinstance(result, pd.DataFrame)

    def test_alpha101(self):
        panel = _make_panel(["close"])
        result = compute("alpha101_101", panel)
        assert isinstance(result, pd.DataFrame)
```

### 运行测试

```bash
python3 -m pytest tests/factors/test_alpha101.py -v
```

Expected: 6 passed

---

## Task 3: Sector-dependent alpha 处理

**关键发现：** 19 个 alpha 标记了 `requires_sector: True`，但 Vibe-Trading 的 `_ind_neutralize` 实现已有**优雅降级**：
- `panel.get("sector")` 缺失时返回 `None`
- 自动降级为**全局截面去均值**（subtract row mean）
- 这些 alpha 的 `columns_required` **不包含 `sector`**，`factor_tool` 的 missing inputs 检测不会拦截

**结论：101 个 alpha 全部可以直接运行，无需 sector 数据。** 行业中性化效果降级为全局去均值（对中低频策略通常可接受）。

**处理策略:**
1. **不删除这些文件** —— 保持 Vibe-Trading 源码完整性
2. **保持 `requires_sector: True` 标记** —— 未来如需精确行业中性化，Agent 可识别并补充 sector 数据
3. **当前零改动** —— 降级逻辑已在源码中，直接可用

### 验证 sector alpha 降级运行

```python
# tests/factors/test_alpha101_sector.py
import numpy as np
import pandas as pd
from factors.registry import compute


def test_sector_alpha_degraded_runs_without_sector():
    """Alpha requiring sector should run without sector via degraded global demean."""
    dates = pd.date_range("2023-01-01", periods=100, freq="D")
    close = pd.DataFrame({
        "SPY": 100 + np.cumsum(np.random.randn(100) * 0.5),
        "QQQ": 100 + np.cumsum(np.random.randn(100) * 0.5),
    }, index=dates)
    panel = {"close": close}
    # alpha101_048 requires sector but has degraded fallback — should succeed
    result = compute("alpha101_048", panel)
    assert isinstance(result, pd.DataFrame)
    assert result.shape[0] == 100
```

---

## Task 4: 全量 dry-run 验证

**目标:** 验证全部 101 个 alpha 都能被正确注册，且 `factor_tool.py --action bench_category` 能处理整族因子。

### 验证脚本

```bash
# 1. 确认注册数量
python3 -c "
from factors.registry import list_factors
alphas = [f for f in list_factors() if f['category'] == 'alpha101']
print(f'alpha101 registered: {len(alphas)}')
assert len(alphas) == 101
"

# 2. 生成合成数据并 bench_category
python3 << 'PYEOF'
import numpy as np
import pandas as pd
import subprocess, sys, tempfile, json
from pathlib import Path

# Build synthetic panel with all fields needed by alpha101
fields = ["open", "high", "low", "close", "volume", "vwap"]
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
    data[(sym, "vwap")] = base + np.random.randn(300) * 0.05

df = pd.DataFrame(data, index=dates)
df.columns = pd.MultiIndex.from_tuples(df.columns)

with tempfile.TemporaryDirectory() as tmp:
    panel_path = Path(tmp) / "panel.parquet"
    df.to_parquet(panel_path)
    out_dir = Path(tmp) / "bench"
    
    result = subprocess.run([
        sys.executable, "tools/factor_tool.py",
        "--action", "bench_category",
        "--category", "alpha101",
        "--data", str(panel_path),
        "--out-dir", str(out_dir),
    ], capture_output=True, text=True)
    
    print(result.stdout)
    if result.returncode != 0:
        print("STDERR:", result.stderr)
    
    # Load summary
    summary_path = out_dir / "bench_summary_alpha101.json"
    with open(summary_path) as f:
        summary = json.load(f)
    
    print(f"\nBenched {len(summary)} alpha101 factors")
    # All 101 alphas should succeed — sector-dependent ones degrade to global demean
    success = sum(1 for v in summary.values() if "error_type" not in v)
    failed = sum(1 for v in summary.values() if "error_type" in v)
    print(f"  Success: {success}, Failed: {failed}")
    assert success == 101, f"Expected all 101 to succeed, got {success}"
PYEOF
```

**期望结果:**
- **全部 101 个 alpha 成功 bench**
- 19 个 sector-dependent alpha 自动降级为全局去均值，不会失败
- `bench_summary_alpha101.json` 成功生成

---

## Task 5: 集成验证

### 验证清单

- [ ] `factor_tool.py --action list` 返回 107 个因子（6 academic + 101 alpha101）
- [ ] `factor_tool.py --action list --category alpha101` 返回 101 个因子
- [ ] `factor_tool.py --action bench --factor alpha101_001` 成功计算 IC/IR
- [ ] `factor_tool.py --action signal --factor alpha101_001` 输出 signal.parquet
- [ ] `factor_tool.py --action bench_category --category alpha101` 处理全部 101 个因子
- [ ] 运行 `scripts/verify_factor_backtest.sh` 仍通过（不破坏 Phase 1）
- [ ] `tests/factors/` 全部测试通过（Phase 1 + Phase 2）

---

## Task 6: Commit

```bash
git add factors/zoo/alpha101/ tests/factors/test_alpha101.py tests/factors/test_alpha101_sector.py
git commit -m "feat(factors): port Vibe-Trading alpha101 (101 alphas)

- Bulk import 101 alpha files from Vibe-Trading
- Import path: src.factors.base -> factors.core.ops
- auto_register_zoo picks up alpha101/ automatically
- 19 sector-dependent alphas degrade to global demean when sector absent (no failures)
- Sample tests for 6 representative alphas (001, 002, 003, 010, 050, 101)
- bench_category alpha101 verifies full-family evaluation"
```

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 批量下载 101 个文件时网络超时 | 中 | 搬运不完整 | 脚本中加入重试逻辑；下载后计数验证 |
| 某些 alpha 使用 ops.py 中未实现的算子 | 低 | 运行时错误 | 抽样测试覆盖多种算子组合；全量 dry-run 暴露问题 |
| Python 3.9 语法兼容性（如 `|` union type） | 低 | 导入失败 | 抽样测试覆盖导入；CI 自动检测 |

---

## 工作量估算

| 任务 | 预估时间 |
|------|---------|
| Task 1: 批量搬运脚本 + 执行 | 15 min |
| Task 2: 抽样测试编写 + 运行 | 20 min |
| Task 3: Sector alpha 降级运行验证 | 10 min |
| Task 4: 全量 dry-run 验证 | 15 min |
| Task 5: 集成验证 | 10 min |
| Task 6: Commit | 5 min |
| **总计** | **~75 min** |
