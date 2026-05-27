# factors/ 模块设计文档 v2

Date: 2026-05-27  
Scope: Fragment F04 — Alpha Zoo（因子库）  
Status: Draft — pending revised implementation plan

---

## 1. 背景与动机

当前 `data_engineer` / `quant_analyst` 每次从零构建因子，重复造轮子。

本模块从 Vibe-Trading (`https://github.com/HKUDS/Vibe-Trading`) 搬运经典因子库，目标：
- 搬运 Vibe-Trading `agent/src/factors/` 的完整因子实现
- 适配到 Quant Cluster 的 `@factor` 注册机制 + `factor_tool.py` CLI
- 与现有 `backtest_tool.py` 无缝衔接

---

## 2. 目标市场优先级

| 阶段 | 因子族 | Vibe-Trading 源路径 | 说明 | 优先级 |
|------|--------|---------------------|------|--------|
| 1 | `academic` | `agent/src/factors/zoo/academic/` | 完整 FF5 + Carhart + MKT-RF。先搬，验证适配层。 | P0 |
| 2 | `alpha101` | `agent/src/factors/zoo/alpha101/` | 101 Formulaic Alphas。搬运后可直接使用。 | P1 |
| 3 | `gtja191` | `agent/src/factors/zoo/gtja191/` | 国泰君安 191 短周期因子。A股导向，挖掘可迁移因子。 | P2 |

---

## 3. 搬运策略：Importer-based 轻量适配

### 3.1 为什么不做 AST 解析？

Vibe-Trading 的 registry 使用 AST 解析 `__alpha_meta__` + Pydantic 验证。但我们选择**不搬运 registry**，原因是：
- AST 解析增加脆弱性（函数重命名、条件导入会误导）
- Pydantic 是新增外部依赖
- `@factor` 装饰器更简洁，元数据与代码在一起，Agent 读源码时一目了然

### 3.2 适配层设计

**Vibe-Trading 原始格式**：
```python
# zoo/academic/carhart_mom.py
from src.factors.base import delta, safe_div

__alpha_meta__ = {
    'id': 'academic_carhart_mom',
    'columns_required': ['close'],
    ...
}

def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel['close']
    ...
```

**适配方式**：
1. 搬运原始文件到 `factors/zoo/academic/carhart_mom.py`
2. 仅批量替换 import 路径：`src.factors.base` → `factors.core.ops`
3. 每个 zoo 目录的 `__init__.py` 作为注册入口：
   - 遍历该目录下所有 `.py` 文件
   - 导入模块，读取 `__alpha_meta__` 和 `compute`
   - 用 `@factor` 装饰器包装 `compute`，注册到全局 REGISTRY

**关键兼容性**：
- `compute(panel: dict[str, pd.DataFrame])` 的签名与我们的 `data: dict[str, pd.DataFrame]` 完全兼容
- `panel` 就是 `data` — key 是 field name（close/volume），value 是 wide DataFrame

### 3.3 目录结构

```
factors/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── meta.py              # @factor 装饰器 + FactorMeta（保留）
│   └── ops.py               # 搬运 Vibe-Trading base.py 全部算子
├── zoo/
│   ├── __init__.py          # zoo 根入口
│   ├── academic/
│   │   ├── __init__.py      # 注册入口：遍历目录，@factor 包装所有 compute
│   │   ├── carhart_mom.py   # 搬运（仅改 import 路径）
│   │   ├── smb.py           # 搬运
│   │   ├── hml.py           # 搬运
│   │   ├── rmw.py           # 搬运
│   │   ├── cma.py           # 搬运
│   │   └── mkt_rf.py        # 搬运
│   ├── alpha101/
│   │   ├── __init__.py      # 注册入口
│   │   ├── alpha_001.py     # 搬运（101 个文件）
│   │   ├── alpha_002.py
│   │   └── ...
│   └── gtja191/
│       ├── __init__.py      # 注册入口
│       └── ...              # 搬运（191 个文件）
├── registry.py              # 全局注册表 + lazy compute
├── bench_runner.py          # IC/IR + alive/reversed/dead 分类
└── zoo_adapter.py           # 适配层：读取 __alpha_meta__，@factor 包装

tools/
└── factor_tool.py           # Agent CLI 入口
```

---

## 4. 核心抽象

### 4.1 面板数据约定（保留）

所有因子函数的输入输出统一为 **panel DataFrame**：

```
index   = DatetimeIndex（日期）
columns = 单级 Index（symbol 代码）
```

`factor_tool.py` 接收 `ohlcv_panel.parquet`（MultiIndex columns: symbol × field），内部拆分为 `dict[str, pd.DataFrame]` 后传入 `compute(panel)`。

### 4.2 @factor 装饰器（保留）

```python
# factors/core/meta.py
@dataclass
class FactorMeta:
    name: str
    category: str
    inputs: list[str]
    outputs: list[str]
    description: str
    compute_fn: Callable

REGISTRY: dict[str, FactorMeta] = {}

def factor(name, category, inputs, outputs, description=""):
    ...
```

### 4.3 zoo_adapter.py — 适配层

```python
# factors/zoo_adapter.py
"""Adapt Vibe-Trading zoo modules to @factor registry.

Scans factors/zoo/ directories, imports each alpha module,
reads __alpha_meta__, and registers a @factor-wrapped compute.
"""

import importlib
import pkgutil
from pathlib import Path

from factors.core.meta import factor, REGISTRY


def _register_zoo_module(module_name: str, category: str) -> None:
    """Import a zoo module and register its compute function."""
    mod = importlib.import_module(module_name)
    if not hasattr(mod, '__alpha_meta__') or not hasattr(mod, 'compute'):
        return

    meta = mod.__alpha_meta__
    compute_fn = mod.compute

    # Map Vibe-Trading meta to @factor parameters
    alpha_id = meta['id']
    columns_required = meta.get('columns_required', [])
    nickname = meta.get('nickname', alpha_id)

    # Wrap compute to accept our data dict format
    def _wrapped_compute(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        # data 和 panel 格式一致：dict[field_name -> wide DataFrame]
        return compute_fn(data)

    # Register manually (bypass decorator to avoid redefining function)
    from factors.core.meta import FactorMeta
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
    for zoo_dir in zoo_root.iterdir():
        if not zoo_dir.is_dir() or zoo_dir.name.startswith('_'):
            continue
        category = zoo_dir.name
        for py_file in sorted(zoo_dir.glob('*.py')):
            if py_file.name.startswith('_'):
                continue
            module_name = f"factors.zoo.{category}.{py_file.stem}"
            try:
                _register_zoo_module(module_name, category)
            except Exception as exc:
                logger.warning(f"Failed to register {module_name}: {exc}")
```

---

## 5. 搬运清单

### 5.1 必搬：base.py 算子

Vibe-Trading `agent/src/factors/base.py` 包含以下算子，alpha101/gtja191 重度依赖：

| 算子 | 说明 |
|------|------|
| `rank(df)` | 截面排名（0-1） |
| `scale(df, a=1.0)` | L1 归一化 |
| `ts_rank(df, n)` | 滚动排名 |
| `ts_corr(x, y, n)` | 滚动相关系数 |
| `ts_cov(x, y, n)` | 滚动协方差 |
| `ts_mean(df, n)` | 滚动均值 |
| `ts_std(df, n)` | 滚动标准差 |
| `ts_max(df, n)` | 滚动最大值 |
| `ts_min(df, n)` | 滚动最小值 |
| `ts_argmax(df, n)` | 滚动 argmax |
| `ts_argmin(df, n)` | 滚动 argmin |
| `delta(df, d)` | 差分（d ≥ 1） |
| `safe_div(a, b)` | 安全除法（b=0 → NaN） |
| `signed_power(x, e)` | sign(x) * |x|^e |
| `decay_linear(df, n)` | 线性衰减加权 |

搬运到 `factors/core/ops.py`。

### 5.2 Phase 1 搬运：academic

从 `agent/src/factors/zoo/academic/` 搬运：

| 文件 | 因子 | 所需数据 |
|------|------|---------|
| `carhart_mom.py` | UMD 动量 | close |
| `smb.py` | SMB（市值因子）| close + market_cap（基本面）|
| `hml.py` | HML（账面市值比）| close + book_value（基本面）|
| `rmw.py` | RMW（盈利能力）| close + profitability（基本面）|
| `cma.py` | CMA（投资风格）| close + investment（基本面）|
| `mkt_rf.py` | 市场超额收益 | close |

**注意**：SMB/HML/RMW/CMA 需要基本面数据（市值、账面价值等）。当前 Data Engineer 只拉 OHLCV，这些因子在基本面数据就绪前会返回 NaN 或报错。`factor_tool.py` 的 `--dry-run` 会检测 `columns_required`，Agent 可选择跳过或请求补充数据。

### 5.3 Phase 2 搬运：alpha101

从 `agent/src/factors/zoo/alpha101/` 搬运全部 101 个文件。

### 5.4 Phase 3 搬运：gtja191

从 `agent/src/factors/zoo/gtja191/` 搬运全部 191 个文件。

---

## 6. 模块详细设计

### 6.1 `core/ops.py` — 搬运 Vibe-Trading base.py

直接搬运 `agent/src/factors/base.py`，仅修改：
- 移除 `Market` enum（当前不需要多市场区分）
- 移除 `Alpha` dataclass 和 `AlphaCompute` Protocol（registry 用不到）
- 保留所有算子函数
- 添加 `__all__` 列表

### 6.2 `zoo_adapter.py` — 适配层

见 Section 4.3。

### 6.3 `registry.py` — 全局注册表

```python
from factors.zoo_adapter import register_all_zoos

# 启动时自动扫描并注册所有 zoo 模块
register_all_zoos()

def list_factors(category: str = "") -> list[dict]: ...
def compute(factor_name: str, data: dict[str, pd.DataFrame]) -> pd.DataFrame: ...
```

### 6.4 `bench_runner.py` — 保留当前实现

与 v1 相同，IC/IR + alive/reversed/dead 分类。

### 6.5 `factor_tool.py` — 保留当前实现

CLI 接口与 v1 相同。factor 名称使用 Vibe-Trading 的 `id`（如 `academic_carhart_mom`, `alpha101_001`）。

---

## 7. Agent 工作流整合

与 v1 相同，但 factor 名称变为 Vibe-Trading 的 `id`：

```bash
# 查询因子
python3 tools/factor_tool.py --action list --category academic
# → academic_carhart_mom, academic_smb, academic_hml, ...

# bench
python3 tools/factor_tool.py \
  --action bench \
  --factor academic_carhart_mom \
  --data /workspace/02_data/ohlcv_panel.parquet

# signal
python3 tools/factor_tool.py \
  --action signal \
  --factor alpha101_001 \
  --data /workspace/02_data/ohlcv_panel.parquet
```

---

## 8. 第一阶段（MVP）范围

| 模块 | 内容 | 工作量 |
|------|------|--------|
| `core/ops.py` | 搬运 Vibe-Trading base.py 全部算子 | 小 |
| `zoo/academic/` | 搬运 6 个 academic 因子文件 | 小 |
| `zoo_adapter.py` | 适配层：扫描 + @factor 包装 | 小 |
| `registry.py` | 自动扫描 + list_factors + compute | 小 |
| `bench_runner.py` | IC/IR + alive/reversed/dead | 小 |
| `factor_tool.py` | CLI: list, bench, bench_category, signal, dry-run | 中 |
| 测试 | `tests/factors/` 单元测试 + 集成测试 | 中 |
| SOUL.md 更新 | hypothesis, data_engineer, quant_analyst | 小 |

**明确不做（第一阶段）**：
- `alpha101` 具体因子搬运（Phase 2）
- `gtja191` 具体因子搬运（Phase 3）

---

## 9. 验证标准

1. `factor_tool.py --action list` 返回 academic 族所有因子（carhart_mom, smb, hml, rmw, cma, mkt_rf）
2. `factor_tool.py --action bench --factor academic_carhart_mom` 成功计算 IC/IR
3. `factor_tool.py --action signal --factor academic_carhart_mom` 输出可喂给 `backtest_tool.py`
4. `dry-run` 模式正确检测缺失列（如 smb 需要 market_cap）
5. 错误返回结构化 JSON，与 `backtest_tool.py` 风格一致
6. `tests/factors/` 单元测试全部通过

---

## 附录：与 convergence 文件 F04 的对照

| F04 要求 | 本设计 v2 |
|---------|----------|
| 引入经典因子库（gtja191/alpha101/academic/qlib158） | ✅ 搬运 Vibe-Trading zoo/ 目录 |
| `factors/registry.py` — AST-only 元数据加载 + lazy compute | ✅ 用 `zoo_adapter.py` 导入时读取 `__alpha_meta__`，@factor 包装后 lazy compute |
| `factors/bench_runner.py` — IC/IR + alive/reversed/dead | ✅ 保留 v1 实现 |
| 封装为 Agent tool：`factor_bench`、`factor_signal` | ✅ `factor_tool.py` CLI |
| `quant_analyst` SOUL.md 更新 | ✅ 详见 Section 7 |
