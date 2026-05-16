# Quant Cluster — Hermes + Kimi Code + IBKR TWS 集成设计

> 日期: 2026-05-15
> 主题: 将 Quant Cluster 的 LLM Provider 切换为 Kimi Code，数据源从 yfinance/FRED 迁移到 IBKR TWS API，引入独立 data_router 服务，实现交互式编排与数据完整性保障。

---

## 1. 设计目标

| 目标 | 说明 |
|------|------|
| **LLM 切换** | 5 个 Hermes Agent 统一使用 Kimi Code（通过 Anthropic API 兼容端点） |
| **数据源迁移** | Data Engineer 从 yfinance/FRED 迁移到 IBKR TWS API（paper, port 7497） |
| **数据完整性** | Agent 必须在获取**全部计划数据**后才能继续，禁止带着残缺数据做研究 |
| **交互式编排** | Kimi Code CLI（Orchestrator）实时掌控流水线，Agent 遇到棘手问题上报而非自行凑数 |
| **旁路咨询** | Agent 之间可通过 Kimi Code CLI 协调，利用 Hermes 的 session 续传能力"断点中继" |
| **可扩展性** | data_router 作为独立服务，未来可扩展数据源、连接池、缓存层 |

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│  用户终端 (macOS)                                                        │
│     │                                                                   │
│     ▼ 自然语言指令                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Kimi Code CLI — Orchestrator / 编排大脑                         │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │   │
│  │  │ DAG 调度    │  │ 错误诊断    │  │ 用户交互 / 自动修复决策  │  │   │
│  │  │ 引擎        │  │ 与重试逻辑   │  │ (换标的/等重连/改需求)   │  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────┘  │   │
│  └────────┬────────────────────┬──────────────────────────────────┘   │
│           │ ① POST /v1/runs    │ ④ 解析响应 / 处理咨询                │
│           │ 或 /v1/chat/comp   │ ←─────────────────────────────────┐  │
│           ▼ (SSE 实时进度)     │                                   │  │
│  ┌─────────────────────────────────────────────────────────────┐    │  │
│  │              Docker Compose 网络                              │    │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │    │  │
│  │  │ hermes-     │  │ hermes-     │  │ hermes-     │          │    │  │
│  │  │ hypothesis  │  │ data_engineer│  │ quant_      │  ...     │    │  │
│  │  │ (8642)      │  │ (8643)      │  │ analyst(8644)│         │    │  │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │    │  │
│  │         │                │                │                 │    │  │
│  │         └────────────────┴────────────────┘                 │    │  │
│  │                          │                                  │    │  │
│  │                          ▼                                  │    │  │
│  │              ┌─────────────────────────┐                    │    │  │
│  │              │    data_router          │                    │    │  │
│  │              │    (port 8888)          │                    │    │  │
│  │              │  ┌───────────────────┐  │                    │    │  │
│  │              │  │ ib_insync ↔ TWS   │  │                    │    │  │
│  │              │  │ 连接管理 + 请求队列 │  │                    │    │  │
│  │              │  │ 5次重试 + 本地缓存  │  │                    │    │  │
│  │              │  └───────────────────┘  │                    │    │  │
│  │              └────────────┬────────────┘                    │    │  │
│  └───────────────────────────┼─────────────────────────────────┘    │  │
│                              │                                       │  │
│                              ▼                                       │  │
│  ┌─────────────────────────────────────────────────────────────┐     │  │
│  │  TWS (macOS 宿主机, port 7497, Paper Trading)                 │     │  │
│  │  "Allow localhost only" = OFF                                  │     │  │
│  │  Trusted IPs: 192.168.0.0/16 (Docker bridge subnet)           │     │  │
│  └─────────────────────────────────────────────────────────────┘     │  │
└─────────────────────────────────────────────────────────────────────────┘
```

**核心设计决策**：
1. **data_router 是 TWS 的唯一连接方**：5 个 Agent 不直接连 TWS，所有 IBKR 数据请求走 data_router REST API。
2. **编排器使用 Runs API + SSE**：`POST /v1/runs` 启动任务（非阻塞），`GET /v1/runs/{id}/events` SSE 订阅实时进度，Agent 完成后解析响应。
3. **断点续传**：利用 Hermes 的 `conversation_history` + `session_id` 机制，Agent 被重新调用时可接续上下文。
4. **文件系统为主通道**：`shared_workspace/` 传递产物，`shared_workspace/00_orchestrator/` 传递咨询/决策状态。

---

## 3. LLM Provider 配置 — Kimi Code

### 3.1 原理

Kimi Code 提供 Anthropic API 兼容端点：
- Base URL: `https://api.kimi.com/coding/`
- 使用 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_API_KEY` 环境变量
- 模型名称可任意指定（如 `claude-sonnet-4`），实际后端路由到 Kimi Code

### 3.2 每个 Agent 的 config.yaml 变更

```yaml
model:
  default: claude-sonnet-4-6    # 名称任意，Kimi Code 会忽略模型名
  provider: anthropic            # 关键：使用 anthropic provider
  base_url: https://api.kimi.com/coding/  # 指向 Kimi Code
  context_length: 200000

# Hermes 内部会通过以下环境变量获取 API key:
# ANTHROPIC_API_KEY (由 docker-compose.yml 注入)
```

### 3.3 docker-compose.yml 环境变量变更

移除 `OPENROUTER_API_KEY`，改为：
```yaml
environment:
  - ANTHROPIC_BASE_URL=https://api.kimi.com/coding/
  - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}   # 从 .env 读取
```

### 3.4 每个 Agent 的模型策略

| Agent | 推荐配置 | 理由 |
|-------|---------|------|
| Hypothesis | Kimi Code (默认) | 文献调研需要强推理 |
| Data Engineer | Kimi Code (默认) | 代码生成能力强 |
| Quant Analyst | Kimi Code (默认) | 数学建模 + 代码 |
| Risk Auditor | Kimi Code (默认) | 审计需要严谨推理 |
| Strategy Writer | Kimi Code (默认) | 长文档生成 |

> 注：Kimi Code 目前只提供一个模型档位，无需像 OpenRouter 那样做模型路由。未来如 Kimi 推出不同档位，可在 config.yaml 中区分。

---

## 4. Data Router 设计

### 4.1 职责边界

| 职责 | data_router 做 | data_router 不做 |
|------|---------------|-----------------|
| ✅ | 管理 ib_insync ↔ TWS 连接 | ❌ 业务决策（换 symbol、换数据源） |
| ✅ | 请求队列 + clientId 管理 | ❌ 无限重试 |
| ✅ | 5 次机械重试（退避：2s, 4s, 8s, 16s, 32s） | ❌ 自修复（如尝试 alternative symbol） |
| ✅ | 本地 SQLite 缓存（避免重复拉取） | ❌ 数据清洗/特征工程 |
| ✅ | 返回结构化错误（含 error_code + suggestion） | ❌ 修改请求参数 |
| ✅ | 路由到不同数据源适配器（IBKR / FRED / Yahoo 等） | ❌ 选择"用哪个数据源"（这是 Agent/Orchestrator 的决策） |

### 4.2 REST API 规范

#### `GET /health`
```json
{
  "status": "ok",
  "tws_connected": true,
  "tws_account": "DU1234567",
  "cache_stats": {"hits": 45, "misses": 12}
}
```

#### `POST /data/historical`

基于 TWS API `reqHistoricalData` 的真实参数设计。所有字段命名与 ib_insync 对齐，确保 Agent 生成的代码可直接映射。

**请求体**：
```json
{
  "contract": {
    "symbol": "QQQ",
    "secType": "ETF",
    "exchange": "SMART",
    "currency": "USD",
    "expiry": "",
    "strike": 0.0,
    "right": "",
    "multiplier": "",
    "localSymbol": "",
    "primaryExchange": "",
    "includeExpired": false
  },
  "endDateTime": "",
  "durationStr": "1 Y",
  "barSizeSetting": "1 day",
  "whatToShow": "TRADES",
  "useRTH": true,
  "formatDate": 1,
  "keepUpToDate": false
}
```

**字段说明（与 TWS API 一一对应）**：

| 字段 | 类型 | 必填 | TWS API 对应 | 说明 |
|------|------|------|-------------|------|
| `contract` | object | ✅ | `Contract` | 合约定义，字段与 ib_insync `Contract` 完全一致 |
| `contract.symbol` | string | ✅ | `symbol` | 标的代码，如 `QQQ`、`SPY`、`VIX` |
| `contract.secType` | string | ✅ | `secType` | `STK`(股票) / `ETF` / `OPT`(期权) / `FUT`(期货) / `CASH`(外汇) / `IND`(指数) / `BOND` |
| `contract.exchange` | string | ✅ | `exchange` | `SMART`(智能路由) / `IDEALPRO`(外汇) / `CBOE` / `NYSE` / `NASDAQ` |
| `contract.currency` | string | ✅ | `currency` | `USD` / `EUR` / `GBP` 等 |
| `contract.expiry` | string | 条件 | `expiry` | 期权/期货到期日，格式 `YYYYMM` 或 `YYYYMMDD` |
| `contract.strike` | float | 条件 | `strike` | 期权行权价 |
| `contract.right` | string | 条件 | `right` | `C`(Call) / `P`(Put)，仅期权 |
| `contract.multiplier` | string | 条件 | `multiplier` | 合约乘数，如 `100` |
| `contract.localSymbol` | string | ❌ | `localSymbol` | 交易所本地代码，如有 |
| `contract.includeExpired` | bool | ❌ | `includeExpired` | 是否包含过期合约（期货/期权） |
| `endDateTime` | string | ❌ | `endDateTime` | 结束时间，格式 `YYYYMMDD-HH:MM:SS` 或 `""`(当前时间) |
| `durationStr` | string | ✅ | `durationStr` | 时间跨度：`n S`/`n D`/`n W`/`n M`/`n Y`。年限制为 1 |
| `barSizeSetting` | string | ✅ | `barSizeSetting` | K线周期：见下方 Valid Bar Sizes |
| `whatToShow` | string | ✅ | `whatToShow` | 数据类型：见下方 Valid whatToShow |
| `useRTH` | bool | ❌ | `useRTH` | `true`=仅常规交易时间，`false`=含盘前盘后 |
| `formatDate` | int | ❌ | `formatDate` | `1`=yyyyMMdd，`2`=Unix timestamp |
| `keepUpToDate` | bool | ❌ | `keepUpToDate` | `true`=订阅实时更新（仅 barSize ≥ 5 secs） |

**Valid Bar Sizes**（与 TWS API 完全一致）：
```
1 secs, 5 secs, 10 secs, 15 secs, 30 secs
1 min, 2 mins, 3 mins, 5 mins, 10 mins, 15 mins, 20 mins, 30 mins
1 hour, 2 hours, 3 hours, 4 hours, 8 hours
1 day, 1 week, 1 month
```

**Valid whatToShow**（按产品类型可用）：

| whatToShow | Stocks | ETFs | Options | Futures | Forex | Indices | Bonds | Crypto |
|-----------|--------|------|---------|---------|-------|---------|-------|--------|
| `TRADES` | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| `MIDPOINT` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| `BID` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| `ASK` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| `BID_ASK` | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| `ADJUSTED_LAST` | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `HISTORICAL_VOLATILITY` | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| `OPTION_IMPLIED_VOLATILITY` | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| `YIELD_BID` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| `YIELD_ASK` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| `YIELD_LAST` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| `SCHEDULE` | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `AGGTRADES` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

> 注：`TRADES` 已做拆股调整，但未做股息调整；`ADJUSTED_LAST` 同时做拆股和股息调整（需 TWS 967+）。

**成功响应**：
```json
{
  "status": "success",
  "request_id": "req-001",
  "source": "ibkr_tws",
  "data_router_request_id": "dr-req-042",
  "contract": {
    "symbol": "QQQ",
    "secType": "ETF",
    "exchange": "SMART",
    "currency": "USD"
  },
  "barSizeSetting": "1 day",
  "whatToShow": "TRADES",
  "durationStr": "1 Y",
  "useRTH": true,
  "startDate": "20240515",
  "endDate": "20250515",
  "timeZone": "EST",
  "rows": 252,
  "bars": [
    {
      "date": "20250515",
      "open": 452.30,
      "high": 455.12,
      "low": 451.80,
      "close": 454.50,
      "volume": 45230000,
      "wap": 453.80,
      "count": 15234
    }
  ],
  "cached": false,
  "fetch_time_ms": 1250
}
```

**Bar 字段说明（与 TWS API `Bar` 对象一致）**：
| 字段 | 类型 | 说明 |
|------|------|------|
| `date` | string | 日期时间，格式取决于 `formatDate` |
| `open` | float | 开盘价/起始价 |
| `high` | float | 最高价 |
| `low` | float | 最低价 |
| `close` | float | 收盘价/最后价 |
| `volume` | int | 成交量（`MIDPOINT`/`BID`/`ASK` 时可能为 N/A） |
| `wap` | float | 加权平均价（Weighted Average Price） |
| `count` | int | 该周期内交易笔数 |

**失败响应（5 次重试后）**：
```json
{
  "status": "error",
  "request_id": "req-001",
  "attempts": 5,
  "error_code": "NO_MARKET_DATA_PERMISSIONS",
  "error_category": "SUBSCRIPTION",
  "tws_error_code": 354,
  "message": "Requested market data is not subscribed. Displaying delayed data.",
  "suggestion": "Subscribe to 'US Securities Snapshot and Futures Value Bundle' in TWS Account Management.",
  "contract": { "symbol": "QQQ", "secType": "ETF", ... }
}
```

**Error Category 映射**：
| data_router error_category | 典型 TWS 错误码 | 说明 |
|---------------------------|----------------|------|
| `SUBSCRIPTION` | 354, 200 | 无市场数据订阅权限 |
| `SYMBOL` | 200, 321 | 标的不存在或已退市 |
| `TIMEOUT` | 504, 162 | TWS 响应超时 |
| `NETWORK` | 1100, 1300 | 网络断开或 TWS 未就绪 |
| `TWS_DISCONNECTED` | 502, 503 | TWS API 连接断开 |
| `RATE_LIMIT` | 506 | 请求频率过高 |
| `INVALID_PARAMS` | 321, 322 | 参数错误（如 barSize 不合法） |
| `DATA_UNAVAILABLE` | 366 | 该时段无数据（如上市前） |

#### `POST /data/batch`
一次性提交多个数据请求，data_router 串行/并行获取，**任一失败则整体返回错误**（支持 `partial_success` 模式可选）。

请求体：
```json
{
  "requests": [
    { "contract": {...}, "durationStr": "1 Y", "barSizeSetting": "1 day", ... },
    { "contract": {...}, "durationStr": "1 Y", "barSizeSetting": "1 day", ... }
  ],
  "parallel": true,
  "partial_success": false
}
```

#### `POST /data/options_chain`
获取期权链定义参数（基于 `reqSecDefOptParams` + `reqHistoricalData`）。

请求体：
```json
{
  "underlyingSymbol": "QQQ",
  "underlyingSecType": "ETF",
  "exchange": "SMART",
  "currency": "USD",
  "expirations": 3,           // 获取前 N 个到期日
  "strikes": 10               // ATM ± N 个行权价
}
```

返回：期权链列表（含隐含波动率、Greeks 等）。

#### `GET /data/fundamentals`
获取基本面数据（基于 `reqFundamentalData`，需要 IBKR 基本面数据订阅）。

查询参数：
```
?symbol=AAPL&secType=STK&reportType=ratios&exchange=SMART
```

`reportType` 可选：`ratios` | `financials` | `estimates` | `calendar`

#### `POST /data/realtime_bars`
订阅实时 5 秒 K线（基于 `reqRealTimeBars`，barSize 固定为 5 秒）。

#### `POST /data/market_data`
订阅实时行情快照（基于 `reqMktData`，返回 bid/ask/last/volume/Greeks 等）。

#### `GET /data/head_timestamp`
获取某合约最早可用的历史数据时间戳（基于 `reqHeadTimeStamp`），用于判断数据范围。

### 4.3 内部架构

```
data_router/
├── main.py                 # FastAPI 应用
├── models.py               # Pydantic 请求/响应模型（与 TWS API 字段一一对应）
├── ibkr/
│   ├── client.py           # ib_insync IB 实例管理 + 异步事件循环
│   ├── connection_pool.py  # clientId 分配（TWS 支持多 clientId，data_router 独占 100-109）
│   ├── historical.py       # reqHistoricalData 封装
│   ├── realtime.py         # reqRealTimeBars / reqMktData 封装
│   ├── options.py          # 期权链 + Greeks 封装
│   ├── fundamentals.py     # reqFundamentalData 封装
│   └── error_mapper.py     # TWS 错误码 → data_router error_category 映射
├── cache/
│   ├── store.py            # SQLite 缓存（表：cache_entries，索引：symbol + secType + barSize + whatToShow + date_range）
│   ├── invalidator.py      # TTL + 手动刷新
│   └── stats.py            # 命中率统计
├── retry/
│   └── backoff.py          # 退避重试（2s, 4s, 8s, 16s, 32s）
├── adapters/
│   └── fallback/           # 备用数据源（当 IBKR 不可用时）
│       ├── yahoo.py        # Yahoo Finance（免费，15分钟延迟）
│       └── fred.py         # FRED 宏观数据
└── requirements.txt        # fastapi, ib-insync, pydantic, uvicorn
```

### 4.4 TWS 连接与 clientId 管理

TWS API 每个连接需要一个唯一的 `clientId`（整数）。data_router 独占 clientId 范围 **100-109**：

```python
# connection_pool.py
class ClientIdPool:
    def __init__(self, start=100, end=109):
        self.available = list(range(start, end + 1))
        self.in_use = set()
        
    def acquire(self) -> int:
        if not self.available:
            raise PoolExhausted("All TWS clientIds in use")
        cid = self.available.pop(0)
        self.in_use.add(cid)
        return cid
        
    def release(self, cid: int):
        self.in_use.discard(cid)
        self.available.append(cid)
```

**连接生命周期**：
1. data_router 启动时创建一个持久连接（clientId=100）用于大部分请求
2. 并发请求时从池中分配额外 clientId
3. TWS 断开时自动重连（指数退避）
4. 所有 Agent 共享 data_router 的单一连接池

### 4.4 TWS 连接配置

```python
# ibkr_client.py 核心逻辑
from ib_insync import IB, Stock, util

class IBKRClient:
    def __init__(self, host='host.docker.internal', port=7497, client_id=1):
        self.ib = IB()
        self.host = host
        self.port = port
        self.client_id = client_id
        
    def connect(self):
        # macOS Docker 容器通过 host.docker.internal 访问宿主机 TWS
        self.ib.connect(self.host, self.port, clientId=self.client_id)
        
    def get_historical_data(self, contract, **kwargs):
        bars = self.ib.reqHistoricalData(contract, **kwargs)
        return util.df(bars)
```

**网络配置要点**：
- Docker Compose 需加 `extra_hosts: ["host.docker.internal:host-gateway"]` 或确保容器能解析 `host.docker.internal`
- macOS 上 Docker Desktop 默认支持 `host.docker.internal` 指向宿主机
- TWS 需配置 Trusted IPs 包含 Docker bridge 子网（如 `192.168.0.0/16`）

---

## 5. 5 个 Hermes Agent 的 SOUL.md 更新

### 5.1 通用变更

所有 Agent 的 SOUL.md 需增加：
1. **Kimi Code 环境说明**："你运行在 Kimi Code 后端，通过 Anthropic API 兼容端点接入。"
2. **data_router 使用规范**：所有数据获取必须通过 `data_router:8888` REST API，禁止直接连接 TWS 或外部数据源。
3. **数据完整性铁律**："你必须获取 data_requirements.json 中列出的**全部数据项**后，才能写入 workspace 并标记任务完成。任何数据缺失都必须上报，禁止凑数。"
4. **自省预算**："遇到数据获取失败时，你最多可尝试 3 轮自修复（如换 symbol、调整时间范围）。3 轮后仍失败，必须输出 `[CONSULTATION_NEEDED]` 并结束当前 run。"
5. **断点续传配合**："当你被重新调用时，会收到完整的 conversation_history。请检查已完成的步骤，从中断点继续，不要重复已完成的工作。"

### 5.2 Hypothesis Agent（变化最大）

**核心变更**：从"简单搜索给假设"升级为**系统性深度文献调研与交叉比对**。

**调研方法论：Phase 1-3 框架**

| Phase | 内容 | 下限要求 |
|-------|------|---------|
| **Phase 1: 多源检索** | 至少访问 3 个信息源，每个源 3-5 条结果 | 总检索量 ≥ 10 条有效结果 |
| **Phase 2: 交叉比对** | Consensus / Divergence / Gap 分析 | 必须标记来源之间的共识和分歧 |
| **Phase 3: 深度推理** | 基于比对结果进行 Chain-of-Thought 推理 | 每个假设必须有证据支撑和质疑回应 |

**信息源优先级矩阵**：

| 优先级 | 信息源 | 访问方式 | 用途 |
|--------|--------|---------|------|
| P0 | Google Scholar | Tavily web_search | 学术论文 |
| P0 | SSRN | WebBridge（需登录） | 金融/经济学工作论文 |
| P0 | QuantConnect | WebBridge（需登录） | 社区策略实现 |
| P1 | Seeking Alpha | WebBridge（需登录） | 市场分析 |
| P1 | arXiv | Tavily web_search | 量化金融预印本 |
| P1 | Fed / BIS / IMF | Tavily web_search | 央行研究报告 |

**输出规范**：
- `hypothesis_{topic}.md` — 假设文档（含 Consensus/Divergence/Gap 分析）
- `data_requirements.json` — 数据需求（带类型标签）
- `references.json` — **参考文献清单**（每条记录含来源、URL、关键发现、可信度评分）

### 5.3 Data Engineer Agent（变化最大）

**核心变更**：
- 数据源从 `yfinance` / `pandas_datareader` 全面迁移到 `data_router` REST API
- 提供按数据类型分类的 `ib_insync` 代码模板（封装在 data_router 中，Agent 调用 API 即可）
- 输出增加 `data_provenance.json` — 记录每项数据的来源、request_id、行数、时间范围

**数据获取工作流**：
```
1. 读取 /workspace/01_hypothesis/data_requirements.json
2. 解析数据需求清单
3. 对每个数据项：
   a. 构造 data_router 请求
   b. 调用 POST /data/historical（或 /data/options_chain 等）
   c. 如果返回 error：
      - 自省分析 error_code
      - 尝试 3 轮自修复（如换 symbol、换 bar_size）
      - 3 轮失败 → 写 consultation 文件 → 返回 [CONSULTATION_NEEDED]
   d. 如果返回 success → 保存数据到 /workspace/02_data/
4. 全部数据获取成功后：
   - 执行数据清洗、特征工程
   - 生成 feature_matrix.parquet + dataset_metadata.json
   - 生成 data_quality_report.md
   - 写 .agent_checkpoint.json（status: success）
```

### 5.4 Quant Analyst Agent

**核心变更**：
- 回测框架优先使用 `backtrader_ib_insync`（与 IBKR data_router 数据格式兼容）
- 回测前必须检查 `.agent_checkpoint.json` 确认 Data Engineer 状态为 success
- 如发现数据异常，走旁路咨询流程（写 consultation → 结束 run → 等修复 → 续传）

### 5.5 Risk Auditor Agent

**核心变更**：
- 过拟合检验数据来源改为 data_router 提供的完整数据集
- PBO 计算需使用 data_router 缓存的原始价格数据

### 5.6 Strategy Writer Agent

**核心变更**：
- SOP 中所有数据来源引用需标注 data_router 的 request_id（用于血缘追踪）
- 如 Risk Auditor 标记 NO-GO，SOP 需包含"策略下线条件"

---

## 6. 编排器（orchestrator.py）改造

### 6.1 架构升级：从同步脚本到异步交互式编排

当前 `orchestrator.py` 是同步阻塞脚本：`chat.completions.create()` 卡住等待 Agent 完成。

新架构：
```python
class InteractiveOrchestrator:
    def __init__(self):
        self.db = StateDB(DB_PATH)
        self.data_router = DataRouterClient("http://data_router:8888")
        
    async def run_pipeline(self, topic: str):
        run_id = generate_run_id()
        self.db.create_run(run_id, topic)
        
        for agent_name in DAG_EXECUTION_ORDER:
            # 1. 检查上游 checkpoint
            if not self.check_upstream_checkpoint(agent_name):
                raise UpstreamNotReady(agent_name)
                
            # 2. 启动 Agent Run（非阻塞）
            run_result = await self.run_agent_with_monitoring(
                agent_name=agent_name,
                topic=topic,
                run_id=run_id
            )
            
            # 3. 解析结果
            if run_result["status"] == "success":
                continue
            elif run_result["status"] == "consultation_needed":
                # 进入交互模式
                resolution = await self.handle_consultation(
                    run_id=run_id,
                    agent_name=agent_name,
                    consultation=run_result["consultation"]
                )
                if resolution["action"] == "resume":
                    # 断点续传：重新调用同一 Agent，带修正指令
                    await self.resume_agent(agent_name, topic, run_id, resolution)
                elif resolution["action"] == "skip":
                    continue
                elif resolution["action"] == "abort":
                    self.db.update_run_status(run_id, "failed")
                    return
                    
    async def run_agent_with_monitoring(self, agent_name, topic, run_id):
        """启动 Agent，SSE 监听进度，等待完成或咨询信号"""
        soul = read_soul_md(agent_name)
        prompt = build_prompt(agent_name, topic, run_id)
        
        # 使用 Runs API 启动（非阻塞）
        hermes_run = await self.hermes_client.create_run(
            port=AGENTS[agent_name]["port"],
            session_id=f"{run_id}_{agent_name}",
            instructions=soul,
            input=prompt
        )
        
        # SSE 订阅进度
        async for event in self.hermes_client.stream_events(hermes_run["run_id"]):
            self.log_progress(agent_name, event)
            
        # 获取最终结果
        result = await self.hermes_client.get_run(hermes_run["run_id"])
        return self.parse_result(result)
```

### 6.2 CLI 交互界面

```bash
# 启动流水线
$ python orchestrator.py run --topic "QQQ Momentum"

# 输出示例
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚀 启动流水线: QQQ Momentum
Run ID: run_20260515_143022
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▶️  阶段 1/5: hypothesis
   [14:30:22] Run started: run_abc123
   [14:30:45] Tool: web_search → "momentum strategy academic research"
   [14:31:20] Tool: web_search → "mean reversion QQQ ETF"
   [14:32:15] ✅ Completed — 3 hypotheses generated

▶️  阶段 2/5: data_engineer
   [14:32:18] Run started: run_def456
   [14:32:30] Tool: ipython → "requests.post('http://data_router:8888/data/historical', ...)"
   [14:32:35] ✅ QQQ daily — 504 rows cached
   [14:32:38] ✅ VIX daily — 504 rows cached
   [14:32:42] ❌ TNX daily — NO_MARKET_DATA_SUBSCRIPTION
   [14:32:45] Self-repair attempt 1/3: ^TNX → ❌
   [14:32:50] Self-repair attempt 2/3: FRED:DGS10 → ❌
   [14:32:55] Self-repair attempt 3/3: ^IRX → ✅
   [14:33:10] ✅ All data fetched — feature_matrix_v1.parquet saved

▶️  阶段 3/5: quant_analyst ...
```

### 6.3 错误交互模式

```bash
▶️  阶段 2/5: data_engineer
   ...
   [14:35:00] ❌ TNX daily — FAILED_AFTER_5_RETRIES
   [14:35:05] Self-repair 1/3: ^TNX → ❌
   [14:35:10] Self-repair 2/3: FRED:DGS10 → ❌
   [14:35:15] Self-repair 3/3: ^IRX → ❌

⚠️  [CONSULTATION_NEEDED] data_engineer 需要决策

   问题: 10年期国债收益率数据无法获取
   已尝试: TNX, ^TNX, FRED:DGS10, ^IRX
   已成功: QQQ(504条), VIX(504条), SPY(504条)
   影响: 策略缺少利率宏观因子

   选项:
     [1] 使用 FRED API 直接获取 DGS10（绕过 data_router）
     [2] 使用 ^TNX 的 15分钟延迟数据（免费档位）
     [3] 跳过利率因子，用已有数据继续
     [4] 手动提供数据文件路径
     [5] 中止当前研究

你的选择 [1-5]: 3

> 选择 3: 跳过利率因子
> Kimi Code CLI: "收到。更新 data_requirements.json，移除 TNX 需求，重新调用 data_engineer..."

▶️  data_engineer (resume from checkpoint)
   [14:36:00] ✅ All data fetched (without TNX)
   ...
```

---

## 7. 数据契约 — Agent 间信息传递协议

### 7.1 文件传递（主通道）

保持 `shared_workspace/` 文件系统传递，但增加严格契约：

```
shared_workspace/
├── 00_orchestrator/              # 新增：编排器状态目录
│   ├── pending_decisions.json     # 待决策队列
│   ├── consultation_log.json      # 咨询历史
│   └── run_status.json            # 当前 run 状态
├── 01_hypothesis/
│   ├── hypothesis_{topic}.md
│   └── data_requirements.json     # 带数据类型标签
├── 02_data/
│   ├── feature_matrix_{version}.parquet
│   ├── dataset_metadata.json
│   ├── data_quality_report_{version}.md
│   └── .agent_checkpoint.json     # 新增：Agent 完成标记
├── 03_backtest/
│   ├── backtest_results_{strategy}.json
│   ├── backtest_report_{strategy}.md
│   └── .agent_checkpoint.json
├── 04_risk/
│   ├── go_no_go_verdict.md
│   └── .agent_checkpoint.json
└── 05_strategy/
    ├── trading_sop_{strategy}.md
    └── .agent_checkpoint.json
```

### 7.2 data_requirements.json 格式（增强版）

```json
{
  "data_contract_version": "1.0",
  "run_id": "run_20260515_143022",
  "topic": "QQQ Momentum vs Mean Reversion",
  "items": [
    {
      "id": "req-001",
      "data_type": "historical_bars",      // historical_bars | options_chain | fundamentals | macro
      "symbol": "QQQ",
      "sec_type": "ETF",
      "exchange": "SMART",
      "currency": "USD",
      "bar_size": "1 day",
      "duration": "2 Y",
      "what_to_show": "TRADES",
      "use_rth": true,
      "required": true,                    // true = 阻塞项，false = 可选
      "purpose": "主标的价格数据，用于动量计算"
    },
    {
      "id": "req-002",
      "data_type": "historical_bars",
      "symbol": "VIX",
      "sec_type": "INDEX",
      "bar_size": "1 day",
      "duration": "2 Y",
      "required": true,
      "purpose": "波动率因子"
    },
    {
      "id": "req-003",
      "data_type": "options_chain",
      "symbol": "QQQ",
      "strike_range": 5,                   // ATM ± 5 strikes
      "expirations": [30, 60, 90],         // DTE
      "required": false,
      "purpose": "期权 IV skew，用于假设 2 的验证"
    }
  ]
}
```

### 7.3 .agent_checkpoint.json 格式

每个 Agent 完成时写入：

```json
{
  "agent": "data_engineer",
  "run_id": "run_20260515_143022",
  "status": "success",                    // success | failed | partial | consultation_needed
  "completed_at": "2026-05-15T14:33:10Z",
  "outputs": [
    {
      "file": "feature_matrix_v1.parquet",
      "path": "/workspace/02_data/feature_matrix_v1.parquet",
      "description": "清洗后特征矩阵",
      "rows": 504,
      "columns": 12
    }
  ],
  "data_provenance": {
    "req-001": {
      "source": "ibkr_tws",
      "data_router_request_id": "dr-req-042",
      "symbol": "QQQ",
      "rows": 504,
      "date_range": ["2024-05-15", "2026-05-15"],
      "cached": false
    },
    "req-002": {
      "source": "ibkr_tws",
      "data_router_request_id": "dr-req-043",
      "symbol": "VIX",
      "rows": 504,
      "cached": false
    }
  },
  "failures": [],                          // 空数组 = 全部成功
  "consultations": [],                     // 如有咨询历史，记录于此
  "next_agent_input_hint": "特征矩阵已就绪，包含动量、波动率、成交量特征。VIX 数据完整可用。"
}
```

### 7.4 旁路咨询文件格式

```json
// /workspace/00_orchestrator/consultation_queue.json
{
  "consultations": [
    {
      "id": "consult-001",
      "from_agent": "quant_analyst",
      "to_agent": "data_engineer",
      "run_id": "run_20260515_143022",
      "status": "pending",                   // pending | resolved | rejected
      "question": "momentum_20d 列存在 5% 极端值 (>5σ)，是否数据清洗时遗漏了拆股复权？",
      "data_sample": { "symbol": "AAPL", "date": "2020-08-31", "value": 125.0 },
      "urgency": "blocking",               // blocking | advisory
      "created_at": "2026-05-15T14:45:00Z"
    }
  ]
}
```

---

## 8. 数据完整性保障机制

### 8.1 核心原则

> **"没有完整数据，就没有研究。"**

Data Engineer Agent 必须在获取 `data_requirements.json` 中所有 `required: true` 的数据项后，才能：
1. 执行数据清洗和特征工程
2. 写入 `feature_matrix.parquet`
3. 生成 `.agent_checkpoint.json`（status: success）

### 8.2 检查点 Gate

编排器在调度下一个 Agent 前，检查：
```python
def check_upstream_ready(agent_name: str) -> bool:
    checkpoint = read_checkpoint(upstream_agent)
    if checkpoint["status"] != "success":
        return False
    if checkpoint["failures"]:
        return False
    # 额外检查：data_requirements 中 required 项是否都在 provenance 中
    required_items = read_data_requirements()["items"]
    for item in required_items:
        if item["required"] and item["id"] not in checkpoint["data_provenance"]:
            return False
    return True
```

### 8.3 失败策略矩阵

| 失败场景 | data_router 行为 | Hermes Agent 行为 | Orchestrator 行为 |
|---------|-----------------|------------------|------------------|
| 网络超时（瞬时） | 5 次退避重试 | 等待结果 | 无感知 |
| TWS 断开 | 返回 TWS_DISCONNECTED | 自省 3 轮 → 上报 | 检查 TWS 状态，指导重连 |
| 无数据订阅 | 返回 NO_MARKET_DATA_SUBSCRIPTION | 自省 3 轮（换 symbol）→ 上报 | 提供替代方案或跳过 |
| 标的不存在 | 返回 INVALID_SYMBOL | 自省 3 轮 → 上报 | 检查标的是否正确 |
| 数据部分缺失 | N/A（data_router 返回完整数据或错误） | 上报 | 评估是否可继续 |

---

## 9. Docker 网络与部署配置

### 9.1 docker-compose.yml 更新

```yaml
version: "3.9"

services:
  # ── Data Router（新增）──────────────────────────────
  data-router:
    build: ./data_router
    container_name: quant-data-router
    ports:
      - "8888:8888"
    environment:
      - TWS_HOST=host.docker.internal
      - TWS_PORT=7497
      - TWS_CLIENT_ID=100
      - CACHE_DB=/app/cache/data_cache.db
    volumes:
      - ./data_router/cache:/app/cache
      - ./shared_workspace:/workspace
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped

  # ── 5 个 Hermes Agent ──────────────────────────────
  hermes-hypothesis:
    image: nousresearch/hermes-agent:latest
    container_name: hermes-hypothesis
    ports:
      - "8642:8642"
    volumes:
      - ./agent_configs/hypothesis:/opt/data
      - ./shared_workspace:/workspace
    environment:
      - HERMES_AUTH_TOKEN=change-me-hypothesis
      - API_SERVER_ENABLED=true
      - API_SERVER_HOST=0.0.0.0
      - API_SERVER_KEY=sk-hypothesis-local
      - ANTHROPIC_BASE_URL=https://api.kimi.com/coding/
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - TAVILY_API_KEY=${TAVILY_API_KEY}
      - PORT=8642
      - HERMES_PROFILE=hypothesis
    depends_on:
      - data-router
    restart: unless-stopped

  hermes-data:
    image: nousresearch/hermes-agent:latest
    container_name: hermes-data
    ports:
      - "8643:8642"
    volumes:
      - ./agent_configs/data_engineer:/opt/data
      - ./shared_workspace:/workspace
    environment:
      - HERMES_AUTH_TOKEN=change-me-data
      - API_SERVER_ENABLED=true
      - API_SERVER_HOST=0.0.0.0
      - API_SERVER_KEY=sk-data-local
      - ANTHROPIC_BASE_URL=https://api.kimi.com/coding/
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - PORT=8642
      - HERMES_PROFILE=data_engineer
    depends_on:
      - data-router
    restart: unless-stopped

  hermes-quant:
    image: nousresearch/hermes-agent:latest
    container_name: hermes-quant
    ports:
      - "8644:8642"
    volumes:
      - ./agent_configs/quant_analyst:/opt/data
      - ./shared_workspace:/workspace
    environment:
      - HERMES_AUTH_TOKEN=change-me-quant
      - API_SERVER_ENABLED=true
      - API_SERVER_HOST=0.0.0.0
      - API_SERVER_KEY=sk-quant-local
      - ANTHROPIC_BASE_URL=https://api.kimi.com/coding/
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - PORT=8642
      - HERMES_PROFILE=quant_analyst
    depends_on:
      - data-router
    restart: unless-stopped

  hermes-risk:
    image: nousresearch/hermes-agent:latest
    container_name: hermes-risk
    ports:
      - "8645:8642"
    volumes:
      - ./agent_configs/risk_auditor:/opt/data
      - ./shared_workspace:/workspace
    environment:
      - HERMES_AUTH_TOKEN=change-me-risk
      - API_SERVER_ENABLED=true
      - API_SERVER_HOST=0.0.0.0
      - API_SERVER_KEY=sk-risk-local
      - ANTHROPIC_BASE_URL=https://api.kimi.com/coding/
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - PORT=8642
      - HERMES_PROFILE=risk_auditor
    depends_on:
      - data-router
    restart: unless-stopped

  hermes-writer:
    image: nousresearch/hermes-agent:latest
    container_name: hermes-writer
    ports:
      - "8646:8642"
    volumes:
      - ./agent_configs/strategy_writer:/opt/data
      - ./shared_workspace:/workspace
    environment:
      - HERMES_AUTH_TOKEN=change-me-writer
      - API_SERVER_ENABLED=true
      - API_SERVER_HOST=0.0.0.0
      - API_SERVER_KEY=sk-writer-local
      - ANTHROPIC_BASE_URL=https://api.kimi.com/coding/
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - PORT=8642
      - HERMES_PROFILE=strategy_writer
    depends_on:
      - data-router
    restart: unless-stopped

  # ── Redis（可选，留给编排层状态）─────────────────────
  redis:
    image: redis:7-alpine
    container_name: quant-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped

volumes:
  redis_data:
```

### 9.2 .env 更新

```bash
# Kimi Code (Anthropic API 兼容端点)
ANTHROPIC_BASE_URL=https://api.kimi.com/coding/
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxx

# Tavily（Hypothesis Agent 搜索用，保留）
TAVILY_API_KEY=tvly-xxxxxxxx

# Data Router（可选，用于本地调试用）
# TWS_HOST=host.docker.internal
# TWS_PORT=7497
```

### 9.3 TWS 配置检查清单

| 配置项 | 要求 | 检查方法 |
|--------|------|---------|
| Enable ActiveX and Socket Clients | ✅ 勾选 | TWS → Edit → Global Configuration → API → Settings |
| Socket port | 7497 (Paper) | 同上 |
| Allow connections from localhost only | ❌ 取消勾选 | 同上 |
| Trusted IPs | 添加 `192.168.0.0/16` | 同上 |
| Create API message log | 可选 | 用于调试 |
| Master API Client ID | 100+ | 避免与 data_router (100) 冲突 |

---

## 10. Web 搜索与浏览器工具 — Kimi WebBridge 集成

### 10.1 能力分层设计

用户要求所有 Agent 在做 web search 时增加 kimi-webbridge skill，从专业信息源检索信息。经调研，WebBridge 本质是**浏览器自动化工具**（基于 Chrome DevTools Protocol），不是搜索引擎。它与现有搜索工具的关系如下：

| 工具 | 定位 | 适用场景 | 技术约束 |
|------|------|---------|---------|
| **Tavily web_search** | 结构化搜索引擎 API | 快速检索公开文献、新闻、网页摘要 | 无需浏览器，API 调用即可 |
| **Hermes 内置 browser** | Playwright 浏览器自动化 | 打开特定网页、提取内容、截图 | 运行在 Docker 沙箱内，使用容器内 Chromium |
| **kimi-webbridge** | 宿主机浏览器自动化 | 访问**需要登录**的网站、利用用户登录态、复杂网页交互 | 需要宿主机 Chrome + 扩展 + 本地服务；Docker 容器内 Agent 需网络通道访问 |

### 10.2 推荐分层策略

```
Agent 需要检索信息时：
    │
    ├─ 信息源是公开的？（Google Scholar, arXiv, FRED, SEC EDGAR...）
    │   ├─ 需要快速结构化摘要？ → 用 Tavily web_search ✅
    │   └─ 需要浏览完整页面？ → 用 Hermes 内置 browser (Playwright) ✅
    │
    └─ 信息源需要登录？（SSRN 全文, Seeking Alpha 付费, IBKR Client Portal...）
        ├─ 简单页面访问？ → 尝试 Hermes 内置 browser（可能因登录态失败）
        └─ 必须利用用户登录态？ → 用 kimi-webbridge（需配置）⚠️
```

### 10.3 Kimi WebBridge 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│  macOS 宿主机                                                │
│  ┌─────────────────┐      ┌─────────────────────────────┐  │
│  │ Chrome/Edge     │◄────►│  Kimi WebBridge 本地守护进程 │  │
│  │ 浏览器 + 扩展    │  CDP  │  (监听 localhost:PORT)      │  │
│  └─────────────────┘      └────────────┬────────────────┘  │
│                                        │                   │
│              ┌─────────────────────────┘                   │
│              │ HTTP/WebSocket 协议                          │
│              ▼                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Docker Compose 网络                                  │   │
│  │  ┌──────────────────────────────────────────────┐    │   │
│  │  │ Hermes Agent (Docker 容器内)                    │    │   │
│  │  │  ┌──────────────┐  ┌────────────────────────┐ │    │   │
│  │  │  │ web_search   │  │ browser (Playwright)   │ │    │   │
│  │  │  │ → Tavily API │  │ → 容器内 Chromium      │ │    │   │
│  │  │  └──────────────┘  └────────────────────────┘ │    │   │
│  │  │         │                   │                  │    │   │
│  │  │         │  ┌────────────────┘                  │    │   │
│  │  │         │  │ 方案A: 配置 browser 连接外部 Chrome │    │   │
│  │  │         │  │       host.docker.internal:9222    │    │   │
│  │  │         │  │       (需 Chrome 开启远程调试)      │    │   │
│  │  │         │  └────────────────────────────────────│    │   │
│  │  │         │                                       │    │   │
│  │  │  ┌──────┴─────────────────────────────────────┐ │    │   │
│  │  │  │ 方案B: 自定义 skill/HTTP 客户端              │ │    │   │
│  │  │  │ → 调用 host.docker.internal:WEBBRIDGE_PORT │ │    │   │
│  │  │  │ → 由宿主机守护进程执行浏览器操作            │ │    │   │
│  │  │  └────────────────────────────────────────────┘ │    │   │
│  │  └──────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 10.4 推荐集成方案（分阶段）

#### 第一阶段：编排器层使用 WebBridge（立即可行）

**Kimi Code CLI（宿主机上运行）已原生支持 WebBridge**：
- 用户已在 Chrome 中安装 WebBridge 扩展
- Kimi Code CLI 可直接发送浏览器操作指令
- **用途**：人工交互时的信息检索、错误诊断时的网页查询

```
场景：Data Engineer 报告 TNX 数据获取失败

Kimi Code CLI → WebBridge → 打开 Chrome → 访问 TWS API 文档
→ 搜索 "TNX market data subscription requirements"
→ 截图/提取结果 → 分析失败原因
→ 指导用户或 Agent 修复
```

#### 第二阶段：Hermes Agent 通过 WebBridge 客户端脚本使用 WebBridge（已验证 ✅）

**验证结果**：
- 宿主机 WebBridge 守护进程监听 `127.0.0.1:10086`
- Docker 容器通过 `host.docker.internal:10086` 可成功访问
- API 协议：**HTTP POST JSON 到 `/command`**（非 WebSocket）
- 已创建封装脚本：`shared_workspace/webbridge_client.py`

**已实现配置**：

`docker-compose.yml` 中所有 Agent 已注入环境变量：
```yaml
environment:
  - WEBBRIDGE_HOST=host.docker.internal
  - WEBBRIDGE_PORT=10086
```

`shared_workspace/webbridge_client.py` 提供封装 API：
```python
# Agent 通过 terminal 工具调用
import subprocess
result = subprocess.run(
    ["python3", "/workspace/webbridge_client.py", "navigate",
     "--url", "https://www.quantconnect.com/",
     "--session", "hypothesis-qc"],
    capture_output=True, text=True
)
```

支持的操作：`navigate`, `snapshot`, `click`, `fill`, `evaluate`, `screenshot`, `list_tabs`, `close_session`, `search_google`, `search_site`

**各 Agent SOUL.md 中的使用规范**（已写入实际文件）：
- Hypothesis: WebBridge 用于访问 SSRN、QuantConnect、Seeking Alpha（需登录的专业网站）
- Data Engineer: WebBridge 用于验证数据异常、查找补充数据
- Quant Analyst: WebBridge 用于 QuantConnect 社区策略验证
- Risk Auditor: WebBridge 用于查阅监管要求
- Strategy Writer: WebBridge 用于交易所规则查询

### 10.5 各 Agent 的 WebBridge 使用场景

| Agent | 需要 WebBridge 的场景 | 优先级 |
|-------|---------------------|--------|
| **Hypothesis** | 访问需要登录的学术数据库（SSRN 全文、Wiley、JSTOR） | 中 |
| **Data Engineer** | 访问 IBKR Client Portal 验证数据订阅（用户说不需要） | 低 |
| **Quant Analyst** | 访问 QuantConnect 社区查看完整策略代码（需登录） | 中 |
| **Risk Auditor** | 访问监管机构网站下载最新监管文件 | 低 |
| **Strategy Writer** | 访问交易所网站获取最新交易规则 | 低 |

### 10.6 实施建议（已验证并实施）

**已完成 ✅**：
1. ✅ WebBridge 客户端脚本 `shared_workspace/webbridge_client.py` 已创建并测试
2. ✅ Docker 容器 → `host.docker.internal:10086/command` 连通性已验证
3. ✅ 5 个 Agent 的 `config.yaml` 已注入 `WEBBRIDGE_HOST` / `WEBBRIDGE_PORT`
4. ✅ 5 个 Agent 的 `SOUL.md` 已更新 WebBridge 使用规范
5. ✅ Tavily web_search 保留（所有 Agent）
6. ✅ Hermes 内置 browser 保留（所有 Agent）

**验证结果摘要**：

| 验证项 | 结果 | 备注 |
|--------|------|------|
| 守护进程端口 | ✅ 10086 | `lsof -i :10086` 确认 |
| Chrome 扩展连接 | ✅ 已连接 | `extension_connected: true` |
| Docker 容器访问 | ✅ 连通 | `docker run --rm alpine curl host.docker.internal:10086/command` 成功 |
| API 协议 | ✅ HTTP POST JSON | `/command` 端点，JSON payload |
| navigate 测试 | ✅ 成功 | 成功打开 example.com |
| list_tabs 测试 | ✅ 成功 | 返回空标签页列表 |
| close_session 测试 | ✅ 成功 | 成功关闭 session |

**无需用户额外操作** — WebBridge 已在运行，配置已就绪。

---

## 11. 实施优先级

| 优先级 | 模块 | 工作量 | 说明 |
|--------|------|--------|------|
| P0 | data_router 服务 | 1-2 天 | FastAPI + ib_insync + SQLite 缓存 |
| P0 | 5 个 Agent config.yaml 更新 | 2 小时 | Kimi Code 接入 |
| P0 | docker-compose.yml 更新 | 2 小时 | 网络、环境变量、depends_on |
| P0 | 5 个 Agent SOUL.md 更新 | 1 天 | data_router 使用规范、数据完整性 |
| P1 | orchestrator.py 异步改造 | 1-2 天 | Runs API + SSE + 交互式 CLI |
| P1 | data_requirements.json 增强 | 4 小时 | 数据类型标签、required 字段 |
| P1 | .agent_checkpoint.json 机制 | 4 小时 | 检查点 gate |
| P2 | 旁路咨询机制 | 1 天 | consultation 文件 + 断点续传 |
| P2 | 回测框架适配 | 4 小时 | backtrader_ib_insync 集成 |
| P3 | 缓存优化 | 4 小时 | 命中率统计、TTL 策略 |
| P3 | 监控/可观测性 | 4 小时 | data_router metrics、Agent 执行时间 |

---

## 12. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Hermes `stream: true` 与 tool progress 事件在实际中不稳定 | 高 | 先实现 polling fallback（GET /v1/runs/{id} 轮询），SSE 作为增强 |
| data_router 连 TWS 的 `host.docker.internal` 在 macOS 上偶尔解析失败 | 中 | 使用 `host-gateway` + 备用 IP 探测 |
| ib_insync 在 Docker 内的异步事件循环与 FastAPI 冲突 | 中 | 在独立线程中运行 ib_insync 事件循环 |
| Kimi Code API 延迟较高（思考模式）导致 Agent 响应变慢 | 中 | 启用 Thinking 模式（Option+T），接受更长的响应时间 |
| 5 个 Hermes 容器内存占用过高 | 中 | 限制每个容器 2GB，不使用 browser 工具的 Agent 可降至 1GB |

---

## 13. 附录：SSE 事件类型参考

Hermes Agent SSE 流中可能出现的事件：

| 事件名 | 说明 | 我们的用途 |
|--------|------|-----------|
| `chat.completion.chunk` | 标准 OpenAI 流式 token | 显示 Agent 正在生成的内容 |
| `hermes.tool.progress` | Agent 开始调用工具 | 显示 "正在获取数据..."、"正在运行回测..." |
| `function_call` | Agent 发起 function call | 追踪工具调用链 |
| `function_call_output` | 工具返回结果 | 追踪数据获取成功/失败 |
| `response.completed` | Agent 完成响应 | 触发结果解析 |

---

*End of Design Document*
