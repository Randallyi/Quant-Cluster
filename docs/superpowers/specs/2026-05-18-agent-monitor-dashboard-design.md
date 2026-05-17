# Agent Monitor Dashboard 设计文档

> 为 Quant Cluster 提供实时图形化监控界面，零侵入现有系统。

## 背景与目标

Quant Cluster 的 5 个 Hermes Agent + Data Router 全部运行在 Docker 中。用户目前只能通过 CLI 命令（`python3 -m orchestrator status`）或询问 Kimi Code 来了解运行状态，无法直观地实时观察每个 agent 在做什么。

**目标**：新增一个独立的 Monitor Dashboard，通过浏览器实时展示：
- Pipeline 整体进度（hypothesis → data → quant → risk → writer）
- 每个 agent 的实时内部活动（API 调用、工具调用、turn 进度）
- 容器健康状态、历史 runs、实时日志流

## 设计原则

1. **零侵入** — 不修改 orchestrator、agent、docker-compose 中任何现有服务
2. **只读观察** — monitor 不写入任何数据，纯旁路监控
3. **生命周期独立** — Dashboard 24/7 运行，无论 pipeline 是否在跑
4. **技术栈一致** — FastAPI + 原生 JS，与现有 Data Router 风格统一

---

## 架构设计

### 新增组件：`monitor/` 目录

```
monitor/
├── main.py              # FastAPI app + WebSocket endpoint
├── collector.py         # 数据收集器：DB 轮询、日志 tail、Docker 状态
├── parser.py            # agent.log 解析器（提取工具调用、turn 信息）
├── state.py             # 内存状态缓存（当前 run、agent 状态快照）
├── static/
│   ├── index.html       # 单页 Dashboard
│   ├── style.css        # 暗色主题
│   └── app.js           # WebSocket 客户端 + 渲染逻辑
├── Dockerfile
└── requirements.txt
```

### 数据流

```
┌─────────────┐     WebSocket      ┌─────────────┐
│  浏览器      │ ◄────────────────► │  monitor    │ :8080
│  Dashboard   │                    │  (FastAPI)  │
└─────────────┘                    └──────┬──────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    │ read                │ tail -f             │ docker ps
                    ▼                     ▼                     ▼
            orchestrator.db      agent_configs/*/logs     Docker socket
            (host bind-mount)    (host bind-mount)        (bind-mount, ro)
                                          │
                                          │ watchdog
                                          ▼
                                    shared_workspace/
                                    (host bind-mount)
```

### docker-compose 追加

```yaml
  monitor:
    build: ./monitor
    container_name: quant-monitor
    ports:
      - "8080:8080"
    volumes:
      - ./orchestrator/orchestrator.db:/data/orchestrator.db:ro
      - ./agent_configs:/data/agent_configs:ro
      - ./shared_workspace:/workspace:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - DB_PATH=/data/orchestrator.db
      - AGENT_CONFIGS_PATH=/data/agent_configs
      - WORKSPACE_PATH=/workspace
      - POLL_INTERVAL=2
    restart: unless-stopped
```

---

## 后端设计

### HTTP API

| Endpoint | 说明 |
|----------|------|
| `GET /` | 返回 Dashboard HTML |
| `GET /api/status` | 当前系统全景（JSON） |
| `GET /api/runs` | 历史 pipeline runs 列表 |
| `GET /api/runs/{run_id}` | 某个 run 的详细状态 |
| `GET /api/agents` | 5 个 agent 的容器健康 + 当前活动 |
| `GET /api/agents/{agent}/logs` | 最近 N 条解析后的日志事件 |
| `WS /ws` | WebSocket 实时事件流 |

### WebSocket 事件协议

所有事件为 JSON，必含字段：`type`, `timestamp`。

#### 1. pipeline 状态变化
```json
{
  "type": "pipeline",
  "run_id": "run_20260518_010000",
  "status": "running",
  "current_stage": "quant_analyst",
  "topic": "动量与反转的边界条件",
  "timestamp": "2026-05-18T01:05:00+08:00"
}
```

#### 2. agent task 状态变化
```json
{
  "type": "agent_task",
  "agent": "quant_analyst",
  "status": "running",
  "run_id": "run_20260518_010000",
  "started_at": "2026-05-18T01:05:00+08:00",
  "timestamp": "..."
}
```

#### 3. agent 实时活动（来自 agent.log tail）
```json
{
  "type": "agent_activity",
  "agent": "hypothesis",
  "session": "api-8641fe00c0ebb1d2",
  "activity": "api_call",
  "call_num": 5,
  "model": "claude-sonnet-4-6",
  "latency_sec": 12.3,
  "timestamp": "..."
}
```

```json
{
  "type": "agent_activity",
  "agent": "hypothesis",
  "session": "api-8641fe00c0ebb1d2",
  "activity": "tool_call",
  "tool": "web_search",
  "duration_sec": 2.1,
  "timestamp": "..."
}
```

```json
{
  "type": "agent_activity",
  "agent": "hypothesis",
  "session": "api-8641fe00c0ebb1d2",
  "activity": "turn_end",
  "reason": "text_response",
  "api_calls": "20/90",
  "tool_turns": 12,
  "timestamp": "..."
}
```

#### 4. 文件系统事件
```json
{
  "type": "fs_event",
  "agent": "quant_analyst",
  "path": "03_backtest/backtest_report_xxx.md",
  "event": "created",
  "timestamp": "..."
}
```

#### 5. 容器健康变化
```json
{
  "type": "container",
  "agent": "hypothesis",
  "status": "running",
  "health": "healthy",
  "uptime_sec": 3600,
  "timestamp": "..."
}
```

#### 6. 心跳
```json
{
  "type": "heartbeat",
  "timestamp": "2026-05-18T01:05:00+08:00"
}
```

### Agent Log 解析策略

解析器用正则表达式从 `agent.log` 提取结构化事件，失败时降级为原始日志行（`activity: "log"`）。

| 日志模式（示例） | activity 类型 | 提取字段 |
|-----------------|--------------|---------|
| `API call #N: model=... latency=X.Ys` | `api_call` | `call_num`, `model`, `latency_sec`, `input_tokens`, `output_tokens` |
| `tool <name> completed (X.Xs, N chars)` | `tool_call` | `tool`, `duration_sec`, `output_chars` |
| `Turn ended: reason=... api_calls=N/90 tool_turns=M` | `turn_end` | `reason`, `api_calls`, `tool_turns`, `response_len` |
| `conversation turn: session=... msg='...'` | `turn_start` | `session`, `model`, `history_len`, `msg_preview` |
| `context compression started/done` | `compression` | `session`, `tokens_before`, `tokens_after` |
| `run_agent: conversation turn:` | `session_start` | `session` |

### 数据源映射

| 展示内容 | 实际来源 | 获取方式 | 频率 |
|---------|---------|---------|------|
| Pipeline 阶段状态 | `orchestrator.db` → `agent_tasks` | SQLite 只读查询 | 轮询 2s |
| Run 历史列表 | `orchestrator.db` → `pipeline_runs` | SQLite 只读查询 | 轮询 10s |
| Agent 容器健康 | Docker Engine API | `GET /containers/json` via socket | 轮询 5s |
| Agent 实时活动 | `agent_configs/{agent}/logs/agent.log` | `tail -f` + `watchdog` | 实时（文件事件驱动） |
| Workspace 文件变化 | `shared_workspace/` | `watchdog` Observer | 实时 |
| Consultation 告警 | `orchestrator.db` → `consultations` | SQLite 只读查询 | 轮询 2s |

### SQLite 只读连接

orchestrator.db 可能被 orchestrator 以 WAL 模式打开。monitor 使用 URI 模式只读连接：

```python
sqlite3.connect("file:/data/orchestrator.db?mode=ro", uri=True)
```

确保不持有写锁，不影响 orchestrator 正常写入。

---

## 前端设计

### 布局

暗色主题，视觉风格与现有 HTML report 统一。

```
┌─────────────────────────────────────────────────────────────┐
│  🔷 Quant Cluster Monitor                    [🟢 Live]  ⚙️ │
├────────────┬────────────────────────────────────────────────┤
│            │  Pipeline: 动量与反转的边界条件                 │
│  AGENTS    │  ┌─────┐   ┌─────┐   ┌─────┐   ┌─────┐      │
│  ───────── │  │ hypo│──▶│data │──▶│quant│──▶│risk │──▶... │
│  🟢 hypo   │  │ ✅  │   │ 🔄  │   │ ⏳  │   │ ⏳  │      │
│  🟢 data   │  └─────┘   └─────┘   └─────┘   └─────┘      │
│  🟡 quant  │                                                │
│  🟢 risk   │  ──────── 实时活动 ────────                   │
│  🟢 writer │                                                │
│            │  [quant] API call #12  latency: 45.2s        │
│  DATA      │  [quant] tool write_file completed (0.8s)    │
│  ROUTER    │  [hypo] Turn ended (budget 20/90)            │
│  🟢 Online │                                                │
│            │                                                │
├────────────┤  ──────── Agent 详情 ────────                │
│ RUNS       │  📋 quant_analyst                             │
│ ─────────  │  Status: running (2m 30s)                    │
│ # run_...  │  Session: api-8641fe00...                     │
│ # run_...  │  Current turn: 12  |  API calls: 12/90       │
│            │  Recent tools: write_file, write_file, ...   │
│            │                                                │
│            │  [实时日志流 ▼]                               │
│            │  09:02:56 API call #16 latency=124.0s        │
│            │  09:02:57 tool write_file completed          │
│            │  09:04:05 API call #17 latency=68.4s         │
│            │  ...                                         │
└────────────┴────────────────────────────────────────────────┘
```

### 组件

| 区域 | 内容 | 交互 |
|------|------|------|
| **顶部栏** | Pipeline 主题、Live 状态指示器、设置按钮 | — |
| **左侧边栏** | Agent 列表（点击切换详情）、健康指示点、Data Router 状态 | 点击 agent 切换右侧详情 |
| **左侧边栏 - Runs** | 历史 run ID 列表，可点击切换 | 点击加载该 run 的快照 |
| **流程图** | 5 个 stage 卡片 + 箭头，颜色 = 状态 | 悬停显示简要信息 |
| **实时活动** | 最近 5 条跨 agent 活动，自动滚动 | — |
| **Agent 详情** | 当前选中 agent 的状态、运行时长、session ID、turn/预算统计、最近工具 | — |
| **日志流** | 该 agent 的实时日志 tail（最后 50 行），自动滚动到底部 | 可展开/收起 |

### 状态颜色

| 状态 | 颜色 | 说明 |
|------|------|------|
| pending / 未开始 | ⬜ `#888` 灰色 | — |
| running | 🟡 `#f0ad4e` 黄色 + 脉冲动画 | 当前正在执行的 stage |
| success / completed | 🟢 `#5cb85c` 绿色 | 已完成 |
| failed | 🔴 `#d9534f` 红色 | 失败 |
| consultation_needed | 🟣 `#9b59b6` 紫色 | 需要人工决策 |
| skipped | ⚪ `#bbb` 浅灰 | 被跳过 |

### 技术选型

- **纯原生 JS**（无 React/Vue），预计 ~500 行
- **CSS Grid/Flexbox** 响应式布局
- **WebSocket 重连**：断线后 3 秒自动重连，指数退避（最大 30s）
- **日志流节流**：如果 1 秒内收到超过 20 条日志，合并为 "+N events" 提示，避免前端卡顿
- **暗色主题变量**：通过 CSS 变量统一定义，便于未来切换主题

---

## 边界情况与错误处理

| 场景 | 处理 |
|------|------|
| orchestrator.db 不存在 | Dashboard 正常显示，pipeline 区域显示 "No runs yet" |
| Agent 未运行过（无 agent.log） | 显示 "No recent activity"，健康状态来自 Docker |
| Agent 日志被轮转/清空 | `tail -f` 自动跟踪新文件，丢失的历史不补 |
| 同时多个 active run | 显示最新的 active run，历史 runs 在侧边栏可切换 |
| monitor 容器重启 | WebSocket 客户端自动重连，状态重新同步 |
| Docker socket 不可用 | 容器健康状态显示 "unknown"，其他功能正常 |
| SQLite 被锁（WAL 模式） | 使用 `mode=ro` URI 连接，只读不影响写方 |
| WebSocket 客户端连接过多 | 后端限制单个 IP 最大 5 个连接 |
| agent.log 格式变化 | 解析失败时降级为原始日志行，不抛异常 |
| 前端长时间无心跳 | 后端 30s 无 pong 主动断开连接 |

---

## 安全考虑

1. **只读挂载** — monitor 对所有数据源均为只读
2. **Docker socket 只读** — `:ro` 挂载，防止误操作容器
3. **无认证（内网使用）** — Dashboard 面向本地开发环境，不暴露公网
4. **日志脱敏** — Hermes 已配置 Secret redaction，日志中不会泄露 API key

---

## 后续可扩展（不在本期 scope）

- [ ] 从 HTML report 嵌入链接跳转到 Dashboard
- [ ] Consultation 决策界面（直接在 Dashboard 里回复 agent 的咨询）
- [ ] Agent 性能统计（平均 latency、token 用量趋势图）
- [ ] 多 run 对比视图
- [ ] 告警通知（WebHook / 桌面通知）
