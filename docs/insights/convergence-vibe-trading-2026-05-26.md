# Fragment Convergence: Vibe-Trading → Quant Cluster

Date: 2026-05-26  
Source: Vibe-Trading (https://github.com/HKUDS/Vibe-Trading) architecture & tech-stack deep-dive  
Analyst: Kimi Code CLI

---

## Fragment Registry

| ID | Fragment | Concept | Component | Priority | Type |
|----|----------|---------|-----------|----------|------|
| F01 | Orchestrator直接REST调用 → Kanban看板调度多Agent | kanban-orchestration | orchestrator/core/scheduler | P1 | refactor |
| F02 | yfinance辅助IBKR调取个股数据（fallback）+ 基本面分析 | multi-source-loader | data_router/loaders | P0 | add |
| F03 | 搬运global_equity.py和options_portfolio.py引擎 + Monte Carlo/Bootstrap/Walk-Forward/Benchmark + run card衔接审计 | backtest-engine-suite | backtest/engines | P0 | add |
| F04 | 引入src/factors/模块，经典因子库（qlib158/alpha101/gtja191/academic） | alpha-zoo | factors/ | P1 | add |
| F05 | Swarm先搁置 | swarm-deferred | — | P3 | defer |
| F06 | 跨run记忆沉淀，archive有全量报告但无记忆索引系统 | persistent-memory | memory/ | P0 | add |
| F07 | 安全边界维持现状（Docker沙箱足够，不直接交易） | security-ok | — | P2 | keep |
| F08 | 前置检查自动化参考，CLI和交互初始化不做 | preflight-checks | orchestrator/preflight.py | P1 | add |

---

## Component Roadmap

### `backtest/engines` (P0 hotspot — 2 fragments)

**现状痛点**：`quant_analyst` Agent每次跑pipeline都从零写回测代码，代码质量不稳定，无标准化验证。

**From F03**:
- [ ] 搬运 Vibe-Trading `agent/backtest/engines/global_equity.py` → `quant-cluster/backtest/engines/global_equity.py`
- [ ] 搬运 Vibe-Trading `agent/backtest/engines/options_portfolio.py` → `quant-cluster/backtest/engines/options_portfolio.py`
- [ ] 搬运 `agent/backtest/engines/base.py` 作为标准化接口基类
- [ ] 搬运验证模块：`validation.py` (Monte Carlo, Bootstrap CI, Walk-Forward)
- [ ] 搬运 `benchmark.py` 用于基准对比 (SPY, CSI 300等)
- [ ] 搬运 `run_card.py` — 每次回测生成 `run_card.json` + `run_card.md`
- [ ] 将引擎封装为 **Agent可调用的tool**（非直接import），参考 Vibe-Trading `agent/src/tools/backtest_tool.py`
- [ ] `run_card.json` 衔接 `risk_auditor` 审计流程 — 审计Agent读取run_card获取可复现信息
- [ ] 为 `quant_analyst` SOUL.md 更新：优先调用标准化引擎，仅在引擎不支持时fallback到自定义代码

**Next**: Say "Run brainstorming on backtest/engines" to design engine-tool interface and agent prompt updates.

---

### `data_router/loaders` (P0 — 1 fragment)

**现状痛点**：单一IBKR数据源，A股支持薄弱，IBKR断开后无fallback。

**From F02**:
- [ ] 在Data Router中新增 `yfinance_loader.py`，支持港股/美股个股日线数据
- [ ] 实现 **Loader Registry + 自动回退链**（参考 Vibe-Trading `agent/backtest/loaders/registry.py`）
  ```
  global_equity chain: yfinance → ibkr
  china_equity chain:  akshare → tushare → ibkr
  ```
- [ ] yfinance提供基本面数据接口（PE、PB、EPS等），供 `hypothesis` / `data_engineer` Agent做基本面分析
- [ ] Data Router路由层增加 `/data/fallback` 元数据接口，Agent可查询当前可用数据源
- [ ] 缓存层扩展：yfinance数据同样进入SQLite cache，key包含source标签

**Next**: Say "Run brainstorming on data_router/loaders" to design registry protocol and cache schema.

---

### `memory/` (P0 — 1 fragment)

**现状痛点**：每次run从零开始，`shared_workspace/archive/` 有全量报告但无提取/索引/检索系统。

**From F06**:
- [ ] 新建 `memory/persistent.py`（参考 Vibe-Trading `agent/src/memory/persistent.py`）
- [ ] 存储布局：`shared_workspace/memory/` 或 `~/.quant-cluster/memory/`
  ```
  MEMORY.md          # 索引（< 200行）
  project_momentum.md   # 带YAML frontmatter的记忆条目
  project_volatility.md
  ```
- [ ] 每个pipeline完成后，自动提取关键发现写入memory（非全量报告，是浓缩洞察）
- [ ] 为每个Agent的SOUL.md增加 **auto-recall** 指令：启动时读取相关memory注入context
- [ ] 支持跨run搜索：关键词评分（metadata权重2.0，body权重1.0）
- [ ] CJK tokenization支持（中文研究主题必须能正确匹配）

**Next**: Say "Run brainstorming on memory/" to design memory extraction pipeline and agent context injection.

---

### `orchestrator/core/scheduler` (P1 — 1 fragment)

**现状痛点**：Orchestrator通过固定DAG直接HTTP调用Hermes容器，灵活性不足，状态难同步。

**From F01**:
- [ ] **研究可行性**：调研 Hermes `kanban-orchestrator` skill（与 `kanban-worker` 配套）
- [ ] 如kanban-orchestrator可用，设计迁移路径：
  ```
  当前: Orchestrator → HTTP POST → Hermes-Agent → 完成
  目标: Orchestrator → kanban_create("task", assignee="hermes-hypothesis") 
        → Hermes 作为kanban worker领取 → kanban_complete / kanban_block
  ```
- [ ] Kanban board 成为**单一事实来源**：任务状态、依赖关系、产出物链接都在board上
- [ ] 保留现有DAG语义，但将 `EXECUTION_ORDER` 映射为 kanban 任务链（parent/child关系）
- [ ] **风险**：需要验证Hermes容器的kanban worker模式是否稳定（kanban-worker skill已在risk_auditor/strategy_writer配置中存在）

**Next**: Say "Run brainstorming on orchestrator/core/scheduler" to evaluate kanban migration path and fallback strategy.

---

### `factors/` (P1 — 1 fragment)

**现状痛点**：data_engineer/quant_analyst每次从零构建因子，重复造轮子。

**From F04**:
- [ ] 新建 `factors/` 模块（参考 Vibe-Trading `agent/src/factors/`）
- [ ] 引入经典因子库（优先度排序）：
  1. `gtja191` — 国泰君安191短周期因子（A股最实用）
  2. `alpha101` — Kakushadze 101 Formulaic Alphas（跨市场通用）
  3. `academic` — Fama-French 5 + Carhart（基准因子）
  4. `qlib158` — Microsoft Qlib（如需要）
- [ ] 实现 `factors/registry.py` — AST-only元数据加载 + lazy compute
- [ ] 实现 `factors/bench_runner.py` — IC/IR计算、alive/reversed/dead分类
- [ ] 封装为Agent tool：`factor_bench`、`factor_signal`
- [ ] `quant_analyst` SOUL.md 更新：优先从因子库选取，再考虑自定义

**Next**: Say "Run brainstorming on factors/" to design factor registry schema and bench integration.

---

### `orchestrator/preflight.py` (P1 — 1 fragment)

**现状痛点**：启动前无自动化检查，常见问题（容器未起、API key失效、端口占用）在pipeline运行中才暴露。

**From F08**:
- [ ] 新建 `orchestrator/preflight.py`（参考 Vibe-Trading `agent/src/preflight.py`）
- [ ] 检查项：
  - Docker容器状态（6个期望容器）
  - 端口占用（8642-8646, 8888, 8080）
  - API key有效性（轻量ping测试）
  - TWS/Data Router连通性
  - WebBridge可达性（port 10086）
  - Workspace权限
- [ ] 集成到 `launch.sh`：启动后自动运行preflight，失败时阻止pipeline启动
- [ ] 集成到 `orchestrator/cli.py health`：扩展现有健康检查，增加preflight维度
- [ ] **明确不做**：交互式 `quant-cluster init` CLI（用户要求）

**Next**: Say "Run brainstorming on orchestrator/preflight" to design check registry and failure reporting.

---

### `security/` (P2 — 1 fragment)

**From F07**:
- [x] **维持现状**。当前每个Hermes在独立Docker容器中运行，已具备进程级隔离。
- [x] Quant Cluster定位为研究工具，不直接执行交易（交易通过IBKR Gateway的Paper Trading），风险敞口可控。
- [ ] 未来如需远程暴露API，再引入路径沙箱 + API Auth（参考 Vibe-Trading `agent/src/security/scanner.py` + `agent/src/tools/path_utils.py`）

---

### Swarm (P3 — deferred)

**From F05**:
- [ ] **明确搁置**。Vibe-Trading的Swarm机制（29预设团队、YAML DAG、streaming）功能强大，但与Quant Cluster的固定5阶段DAG定位不同。
- [ ] 若未来需要动态多Agent评审（如投资委员会辩论），可重新评估。

---

## Unmapped Fragments

| Fragment | Reason |
|----------|--------|
| Vibe-Trading React 19前端 | Quant Cluster的Monitor Dashboard已满足需求，重写为React收益不足 |
| Vibe-Trading MCP Server/Client | 当前架构以Orchestrator为中心，引入MCP增加复杂度 |
| Vibe-Trading Shadow Account | 功能定位不同（交易行为诊断 vs 策略研究） |
| Vibe-Trading 13+ LLM Provider支持 | Quant Cluster专注Kimi Code API，多provider增加维护负担 |
| CLI交互式初始化 (`quant-cluster init`) | 用户明确要求不做 |

---

## Handoff to Brainstorming

每个P0/P1组件都是自包含的设计简报。要进入任一组件的详细设计，说：

> "Run brainstorming on [component-name]"

例如：
- "Run brainstorming on backtest/engines" → 设计引擎-tool接口、run_card衔接审计
- "Run brainstorming on memory/" → 设计记忆提取流水线、agent context注入
- "Run brainstorming on data_router/loaders" → 设计registry协议和cache schema
