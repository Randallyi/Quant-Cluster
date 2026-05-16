# Quant Cluster 🎯

> 5 个 Hermes 协作的量化策略研究自动化流水线

**从假设生成 → 数据工程 → 回测建模 → 风控审计 → 策略撰写，全自动完成。**

---

## 架构概览

Quant Cluster 的独特设计：**Kimi Code 既是入口指挥官，又是每个 Agent 的大脑。**

```
         你 (User)
           │
           ▼  "研究一下动量与反转的边界条件"
    ┌──────────────┐
    │  Kimi Code   │  ←── 理解意图、调用 Orchestrator、汇总结果
    │   (CLI)      │
    └──────┬───────┘
           │
           ▼  python3 -m orchestrator run --topic "..."
    ┌──────────────┐
    │ Orchestrator │  ←── DAG 调度：hypothesis → data → quant → risk → writer
    │   (Python)   │
    └──────┬───────┘
           │ HTTP API (SSE 流式)
           ▼
    ┌────────────────────────────────────────┐
    │      5 Hermes Agent Containers         │
    │  ┌─────────┐  ┌─────────┐  ┌────────┐ │
    │  │hypothesis│  │data_eng │  │ quant  │ │  ...
    │  │:8642    │  │:8643    │  │:8644   │ │
    │  └────┬────┘  └────┬────┘  └───┬────┘ │
    │       │            │           │      │
    │       └────────────┴───────────┘      │
    │                   │                   │
    │                   ▼                   │
    │   ┌───────────────────────────────┐   │
    │   │ 每个 Agent 内部调用 LLM API   │   │
    │   │ ANTHROPIC_BASE_URL            │   │
    │   │  ↓                            │   │
    │   │  Kimi Code (API)              │   │  ←── Agent 的"大脑"
    │   │  完成文献调研 / 写代码 / 审计  │   │
    │   └───────────────────────────────┘   │
    └────────────────────────────────────────┘
           │
           ▼  REST
    ┌──────────────┐
    │ Data Router  │  ←── SQLite Cache + IBKR TWS API
    │  (Port 8888) │
    └──────┬───────┘
           ▼
    ┌──────────────┐
    │ IB Gateway   │  ←── Paper Trading / Live
    │  (Port 7497) │
    └──────────────┘
```

### 为什么这样设计？

| 层级 | 角色 | 说明 |
|------|------|------|
| **你** | 指挥官 | 用自然语言下达研究指令 |
| **Kimi Code (CLI)** | 入口 + 大脑 | 理解你的意图，调用 Orchestrator，把最终结果呈现给你 |
| **Orchestrator** | 调度器 | 按 DAG 顺序调用 5 个 Agent，处理失败重试、断点续跑 |
| **Hermes Agent** | 执行容器 | 接收任务，内部通过 API 再次调用 Kimi Code 完成具体工作 |
| **Kimi Code (API)** | 每个 Agent 的大脑 | 5 个 Agent = 5 个独立的 LLM 会话，各自完成专业任务 |
| **Data Router** | 数据网关 | 统一管理 IBKR 数据，避免 clientId 冲突，SQLite 缓存加速 |
| **WebBridge** | 浏览器桥接 | 宿主机的真实 Chrome，Agent 通过它访问 SSRN、QuantConnect、Seeking Alpha 等需登录网站 |

**一句话总结**：你对着 Kimi Code 说一个策略想法，Kimi Code  orchestrates 5 个专业 Agent——其中 Hypothesis Agent 会打开你的 Chrome 浏览器深入 SSRN、QuantConnect 做文献调研——最终给你一个完整的双语研究报告。

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| **hypothesis** | 文献调研 + 可检验假设 | 研究主题 | 假设报告 (中英双语) + 数据需求清单 |
| **data_engineer** | 数据获取 + 特征工程 | 数据需求 | 特征矩阵 + 数据质量报告 (中英双语) |
| **quant_analyst** | 回测建模 + 绩效分析 | 假设 + 特征矩阵 | 回测结果 + 回测报告 (中英双语) |
| **risk_auditor** | 过拟合检验 + GO/NO-GO | 回测结果 | 审计报告 + 参数稳定性图 (中英双语) |
| **strategy_writer** | 交易 SOP + 知识沉淀 | 审计结论 | 策略文档 + 元数据 (中英双语) |

**Pipeline 完成后自动生成**：
- ✅ 归档报告 + 图表（`shared_workspace/archive/{run_id}/`）
- ✅ 交互式 HTML 报告（暗色主题、双语切换、Dashboard 指标）
- ✅ 中间数据自动清理（释放磁盘空间）

---

## 使用方式

Quant Cluster 支持两种使用模式：

### 模式 A：Kimi Code 自动模式（推荐）

安装项目自带的 Kimi Code skill，然后**用自然语言下达指令**：

```bash
# 安装 skill（符号链接到 Kimi Code skill 目录）
ln -s $(pwd)/.kimi/skills/quant-cluster ~/.kimi/skills/quant-cluster
```

之后你只需要说：

```
你: 研究一下动量与反转的边界条件
Kimi Code: 好的，我来启动 Quant Cluster pipeline...
         [自动检查容器状态 → 启动 → 运行 5 个 Agent → 汇总结果]
         已完成！HTML 报告在 archive/run_xxx/final_report.html
```

Kimi Code 会自动处理所有运维细节：健康检查、容器管理、stage 调度、失败重试。

### 模式 B：CLI 手动模式

直接运行 Orchestrator 命令（适合调试和自定义）：

```bash
python3 -m orchestrator.orchestrator run --topic "你的研究主题"
```

---

## 快速开始

### 1. 前置要求

- [Docker Desktop](https://www.docker.com/products/docker-desktop)
- [IB Gateway](https://www.interactivebrokers.com/en/index.php?f=16457)（Paper Trading，port 7497）
- LLM API Key（支持 Anthropic API 兼容端点，如 [Kimi Code](https://www.kimi.com/code)、OpenRouter）
- [Tavily API Key](https://tavily.com)（Hypothesis Agent 文献调研用）
- **WebBridge**（宿主机 Chrome 浏览器守护进程，port 10086）— Hypothesis Agent 通过它访问需要登录的学术网站

### 2. 配置环境

```bash
cp .env.example .env
# 编辑 .env，填入你的 API keys
# 注意：ANTHROPIC_BASE_URL 指向 Kimi Code API，Agent 们用它作为"大脑"
```

### WebBridge 配置（文献调研必需）

Hypothesis Agent 的文献调研**依赖 WebBridge** 访问需要登录的网站。WebBridge 是运行在宿主机上的 Chrome 浏览器守护进程：

```bash
# 启动 WebBridge（需要单独安装 Kimi Code CLI 的 WebBridge 组件）
# 默认监听 host.docker.internal:10086
# Agent 容器内通过 webbridge_client.py 调用
```

**为什么必须用它？**

| 信息源 | Tavily/web_search | WebBridge |
|--------|-------------------|-----------|
| Google Scholar | 只能拿到标题+摘要 | 可访问完整页面 |
| SSRN | 经常返回空内容 | ✅ 利用宿主机登录态获取全文 |
| QuantConnect | 无法访问社区代码 | ✅ 可浏览论坛和策略实现 |
| Seeking Alpha | 付费墙阻挡 | ✅ 利用已登录态访问 |
| arXiv PDF | 提取失败 | ✅ 直接下载或浏览 HTML 版 |

Agent 会自动选择正确的方式：先用 `web_search` 获取候选链接，对关键链接用 `terminal` → `webbridge_client.py` 获取全文。

### 3. 启动

```bash
bash launch.sh
```

### 4. 健康检查

```bash
python3 -m orchestrator.orchestrator health
```

### 5. 运行 Pipeline

```bash
# 完整跑一个研究主题
python3 -m orchestrator.orchestrator run --topic "动量与反转的边界条件"

# Dry-run（不调用 Agent，验证流程连通性）
python3 -m orchestrator.orchestrator run --topic "测试" --dry-run

# 从中间 stage 恢复（跳过已完成的阶段）
python3 -m orchestrator.orchestrator run --topic "xxx" --from-stage quant_analyst

# 跳过归档（保留 workspace 所有文件）
python3 -m orchestrator.orchestrator run --topic "xxx" --skip-archive
```

### 6. 查看产物

```bash
# 历史 runs
python3 -m orchestrator.orchestrator status

# 打开 HTML 报告
open shared_workspace/archive/run_*/final_report.html
```

### 7. 停止

```bash
bash stop.sh
```

---

## 技术栈

| 组件 | 技术 |
|------|------|
| **入口指挥官** | Kimi Code CLI — 理解用户意图，调用 Orchestrator |
| **Agent 大脑** | Kimi Code API (`https://api.kimi.com/coding/`) — 5 个独立 LLM 会话 |
| **Agent 容器** | [Hermes Agent](https://github.com/NousResearch/hermes) (Docker) — 任务接收 + 工具执行 |
| **Data Router** | Python FastAPI + IBKR TWS API (ib_insync) + SQLite Cache |
| **Orchestrator** | Python asyncio + Rich CLI + Jinja2 HTML Reporter |
| **可视化** | ECharts (CDN) + 暗色主题 CSS |
| **部署** | Docker Compose |

---

## 项目结构

```
quant-cluster/
├── agent_configs/           # 5 个 Agent 的配置
│   ├── hypothesis/SOUL.md   # Agent 指令（中英双语报告要求）
│   ├── hypothesis/config.yaml
│   ├── data_engineer/SOUL.md
│   ├── data_engineer/config.yaml
│   ├── quant_analyst/SOUL.md
│   ├── quant_analyst/config.yaml
│   ├── risk_auditor/SOUL.md
│   ├── risk_auditor/config.yaml
│   ├── strategy_writer/SOUL.md
│   └── strategy_writer/config.yaml
├── data_router/             # IB Gateway REST 数据网关
│   ├── cache/               # SQLite 数据缓存
│   ├── ibkr/                # IBKR 客户端
│   ├── routers/             # FastAPI 路由
│   └── main.py
├── orchestrator/            # Pipeline 编排器
│   ├── core/
│   │   ├── orchestrator.py  # 核心编排逻辑
│   │   ├── dag.py           # Agent 注册 + 依赖图
│   │   ├── html_reporter.py # HTML 报告生成器
│   │   └── state_db.py      # 运行状态数据库
│   └── orchestrator.py      # CLI 入口
├── shared_workspace/        # Agent 产物工作区（运行时创建）
│   └── archive/             # 历史归档
├── docker-compose.yml       # 8 个服务编排
├── launch.sh                # 一键启动
├── stop.sh                  # 一键停止
└── .env.example             # 环境变量模板
```

---

## 核心特性

- **🧠 Kimi Code 双角色**：既是你的入口界面，又是 5 个 Agent 各自的 LLM 大脑
- **🤖 5 Agent 协作**：hypothesis → data_engineer → quant_analyst → risk_auditor → strategy_writer，DAG 依赖自动调度
- **🌐 中英双语报告**：每个 Agent 同时产出中文 + 英文版本，HTML 报告支持语言切换
- **📊 自动可视化**：ECharts Dashboard + 参数热力图 + 权益曲线 + 排列检验图
- **🗄️ 智能归档**：保留报告和图表，清理 GB 级中间数据，每个 run 归档仅 ~10MB
- **🛡️ 归档安全保护**：空 workspace / 归档失败时自动跳过清理，防止误删
- **⏯️ 断点续跑**：`--from-stage` 跳过已完成阶段，从失败处恢复
- **🔍 WebBridge 文献调研**：Hypothesis Agent 通过宿主机 Chrome 访问 SSRN、QuantConnect、Seeking Alpha、arXiv 等，利用真实登录态获取全文
- **📡 IBKR 数据路由**：唯一 IB Gateway 客户端，Agent 通过 REST API 获取数据，避免 clientId 冲突

---

## License

MIT — 详见 [LICENSE](./LICENSE)

---

> ⚠️ **免责声明**：本项目仅用于量化策略研究，不构成任何投资建议。回测结果不代表未来表现。
