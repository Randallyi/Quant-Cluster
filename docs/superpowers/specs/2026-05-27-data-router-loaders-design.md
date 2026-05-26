# Data Router / Loaders 重构设计

> **来源**: Fragment Convergence F02 (`docs/insights/convergence-vibe-trading-2026-05-26.md`)  
> **日期**: 2026-05-27  
> **状态**: 待实现  
> **范围**: `data_router/loaders/` 新建 + `cache/` 扩展 + `routers/` 拆分

---

## 1. 背景与目标

当前 `data_router` 仅有 IBKR 单一数据源，存在以下痛点：
- A 股支持薄弱
- IBKR 断开后无 fallback
- 各 Agent 无法查询数据源健康状态

**目标**：
1. 新增 `yfinance_loader`，支持港股/美股个股日线数据
2. 保留 `akshare_loader` 占位骨架（暂不实现）
3. 各 Loader 独立暴露端点，Agent 调用前自选数据源
4. 统一 cache 表支持多源，自动 migration
5. 新增 `/data/sources` 健康查询接口

---

## 2. 设计决策摘要

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 数据模型 | 标准 `Bar` + `metadata` 扩展字段 | 保证兼容性，同时保留差异字段 |
| 回退链 | 不做 chain 机制，Agent 自选 | 仅 2 个主力源，chain 过度设计 |
| 端点拆分 | 独立端点（/data/ibkr/*, /data/yfinance/*） | 各数据源入参差异大，统一模型别扭 |
| Cache | 统一 SQLite 表，加 `source` 列 | 全局统计方便，避免重复缓存 |
| 现有 /data/historical | 保留 3 个月，内部转发 + deprecation log | 向后兼容 |

---

## 3. 目录结构

```
data_router/
├── loaders/
│   ├── __init__.py
│   ├── base.py              # LoaderProtocol（非强制继承）
│   ├── yfinance_loader.py   # yfinance 数据获取 + 基本面
│   └── akshare_loader.py    # 占位骨架（暂不实现）
├── routers/
│   ├── __init__.py
│   ├── ibkr.py              # ← 从 data.py 拆分：/data/ibkr/historical
│   ├── yfinance.py          # /data/yfinance/historical, /data/yfinance/fundamental/{ticker}
│   └── sources.py           # /data/sources 健康查询
├── cache/
│   ├── db.py                # migration 支持（加 source 列）
│   └── manager.py           # source-aware key + 全局统计
├── models.py                # 新增 YFHistoricalRequest, FundamentalData, SourceHealth
└── main.py                  # 注册新 routers
```

---

## 4. Loader 接口约定

```python
from typing import Protocol, List, Optional
from models import Bar

class LoaderProtocol(Protocol):
    name: str  # "ibkr" | "yfinance" | "akshare"

    def fetch_historical(self, **kwargs) -> List[Bar]:
        """返回标准 Bar，扩展字段由端点包装到 metadata。"""
        ...

    def fetch_fundamental(self, ticker: str) -> Optional[FundamentalData]:
        """可选：基本面数据。不支持则返回 None。"""
        ...

    def health(self) -> dict:
        """返回 {available: bool, latency_ms: int, message: str}"""
        ...
```

**设计意图**：
- 不用抽象基类强制继承，保持各 Loader 入参自由
- `fetch_historical` 返回**标准化后的 Bar**（统一 OHLCV），差异字段通过响应包装层的 `metadata` 透出
- `health()` 供 `/data/sources` 聚合调用

---

## 5. 端点设计

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/data/ibkr/historical` | 现有逻辑迁移，请求参数不变 |
| POST | `/data/yfinance/historical` | 日线数据，入参简化 |
| GET | `/data/yfinance/fundamental/{ticker}` | 基本面快照 |
| GET | `/data/sources` | 各数据源健康状态 + 统计 |

### 5.1 现有端点兼容性

现有 `/data/historical` **保留 3 个月**，内部转发到 `/data/ibkr/historical`，打印 deprecation warning log。Agent 配置可逐步迁移。

---

## 6. 请求/响应模型

### 6.1 新增请求模型

```python
class YFHistoricalRequest(BaseModel):
    ticker: str
    start: str = ""               # YYYY-MM-DD，空则 1 年前
    end: str = ""                 # YYYY-MM-DD，空则昨天
    interval: Literal["1d", "1wk", "1mo"] = "1d"
    auto_adjust: bool = True      # 是否返回复权价

class FundamentalData(BaseModel):
    ticker: str
    market_cap: Optional[float]
    pe_ratio: Optional[float]
    pb_ratio: Optional[float]
    eps: Optional[float]
    dividend_yield: Optional[float]
    last_updated: str             # ISO 时间戳
```

### 6.2 统一响应包装

```python
class DataResponse(BaseModel):
    status: Literal["success", "error"]
    source: str
    request_id: str
    data: List[Bar] | FundamentalData
    metadata: dict = Field(default_factory=dict)
    cached: bool = False
    fetch_time_ms: int = 0
```

`metadata` 作为扩展字段出口，示例：
- yfinance historical: `{"adj_close": [150.2, 151.3, ...], "currency": "USD"}`
- ibkr historical: `{"wap": [...], "count": [...]}`

### 6.3 错误响应

```python
class DataErrorResponse(BaseModel):
    status: Literal["error"]
    source: str
    request_id: str
    error_code: str
    error_category: Literal["NETWORK", "SYMBOL", "RATE_LIMIT", "SUBSCRIPTION", "TIMEOUT", "DATA_UNAVAILABLE", "INVALID_PARAMS"]
    message: str
    suggestion: str
    fallback_available: List[str]  # 告知 Agent 还有哪些源可用
```

---

## 7. Cache 扩展与 Migration

### 7.1 Schema 变更

给 `cache_entries` 表增加 `source` 列：

```sql
ALTER TABLE cache_entries ADD COLUMN source TEXT DEFAULT 'ibkr';
```

### 7.2 自动 Migration

`cache/db.py` 启动时自动检测并执行：

```python
def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute(_CREATE_TABLE_SQL)  # 新表直接带 source 列
    _migrate_add_source_column(conn)  # 旧表自动补列
    return conn

def _migrate_add_source_column(conn: sqlite3.Connection):
    cur = conn.execute("PRAGMA table_info(cache_entries)")
    columns = [row[1] for row in cur.fetchall()]
    if "source" not in columns:
        conn.execute(
            "ALTER TABLE cache_entries ADD COLUMN source TEXT DEFAULT 'ibkr'"
        )
        conn.commit()
```

### 7.3 Cache Key 更新

```python
@staticmethod
def _compute_key(source: str, request) -> str:
    parts = [source, request.contract.symbol, ...]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
```

**向后兼容**：
- `get/set` 增加 `source: str = "ibkr"` 默认参数，现有代码不受影响
- 旧数据（source=NULL）在 migration 后自动变为 `"ibkr"`，key 不变，继续可用
- 新 key 包含 source 前缀，与旧数据不冲突，无需重建

### 7.4 全局统计

`CacheManager.stats()` 扩展为按 source 分组：

```python
def stats(self) -> dict:
    # 返回示例：
    # {
    #   "ibkr": {"entries": 120, "hit_rate": 0.85},
    #   "yfinance": {"entries": 45, "hit_rate": 0.92},
    #   "total": {"entries": 165, "hit_rate": 0.87}
    # }
```

---

## 8. Agent 交互流程

### 8.1 调用前查询

```
GET /data/sources
→ 返回各源可用性、支持市场、延迟、缓存统计
→ Agent 根据目标市场 + available 选源
```

### 8.2 数据源选择策略（建议写入 Agent SOUL.md）

| 目标市场 | 首选 | Fallback |
|----------|------|----------|
| 美股/港股 | IBKR | yfinance |
| A 股 | akshare（暂不支持） | — |

### 8.3 错误处理策略

| error_category | Agent 行为 |
|----------------|-----------|
| `TWS_DISCONNECTED` / `NETWORK` | 可换源重试 |
| `RATE_LIMIT` | 等待后重试同一源 |
| `INVALID_SYMBOL` / `SUBSCRIPTION` | 不换源，直接报错 |
| `DATA_UNAVAILABLE` | 可尝试其他源 |

`fallback_available` 字段让 Agent 无需再次查询 `/data/sources` 即可知道可重试的源。

---

## 9. 数据流

```
Agent
  │
  ├── GET /data/sources ──→ sources.py ──→ 各 Loader.health() + CacheManager.stats()
  │
  ├── POST /data/yfinance/historical ──→ yfinance.py
  │       └── yfinance_loader.fetch_historical()
  │       └── CacheManager.get(source="yfinance")
  │       └── yfinance.download() (miss)
  │       └── CacheManager.set(source="yfinance")
  │       └── DataResponse(metadata={"adj_close": [...]})
  │
  └── GET /data/yfinance/fundamental/AAPL ──→ yfinance.py
          └── yfinance_loader.fetch_fundamental("AAPL")
          └── DataResponse(data=FundamentalData(...))
```

---

## 10. 后续工作

| 序号 | 任务 | 优先级 |
|------|------|--------|
| 1 | 写 implementation plan（调用 writing-plans skill） | P0 |
| 2 | 实现 `loaders/base.py` + `yfinance_loader.py` | P0 |
| 3 | 拆分 `routers/data.py` → `ibkr.py` + 新建 `yfinance.py` + `sources.py` | P0 |
| 4 | Cache migration + source-aware key | P0 |
| 5 | 更新 `models.py` | P0 |
| 6 | 更新 `main.py` 注册新 routers | P0 |
| 7 | 保留 `/data/historical` 兼容 + deprecation log | P1 |
| 8 | 写单元测试 | P1 |
| 9 | 更新 `data_engineer` / `quant_analyst` SOUL.md（数据源调用策略） | P1 |
| 10 | `akshare_loader.py` 占位骨架 | P2 |

---

## 11. 相关文件

- `docs/insights/convergence-vibe-trading-2026-05-26.md` — Fragment Convergence 原文
- `data_router/main.py` — FastAPI 应用入口
- `data_router/routers/data.py` — 现有 historical 端点（将被拆分）
- `data_router/cache/manager.py` — CacheManager（将被扩展）
- `data_router/cache/db.py` — SQLite 初始化（将被扩展）
- `data_router/models.py` — Pydantic 模型（将被扩展）
