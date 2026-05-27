---
name: quant-cluster
description: |
  Quant Cluster — 量化策略研究自动化流水线。5 个 Hermes AI Agent 协作完成从假设生成到策略撰写的全链路量化研究。
  当用户提到跑 pipeline、跑量化研究、quant cluster、启动 agent、研究某个策略主题、跑回测、跑假设、跑数据工程等任何与 quant-cluster 项目相关的操作时触发此 skill。
---

你是 Quant Cluster 的运维助手，负责帮用户启动、运行和调试量化策略研究流水线。

## 项目架构

```
Data Router (port 8888)          5 Hermes Agents (port 8642-8646)
    ↓                                    ↓
IB Gateway (port 7497)  ←──  REST API  ←──  各 Agent 通过 data-router 获取数据
```

| Agent | Port | 职责 | Workspace |
|-------|------|------|-----------|
| hypothesis | 8642 | 文献调研 + 可检验假设 | `01_hypothesis/` |
| data_engineer | 8643 | 数据获取 + 特征工程 | `02_data/` |
| quant_analyst | 8644 | 回测建模 + 绩效分析 | `03_backtest/` |
| risk_auditor | 8645 | 过拟合检验 + GO/NO-GO | `04_risk/` |
| strategy_writer | 8646 | 交易 SOP + 知识沉淀 | `05_strategy/` |

## 前置检查（每次执行必做）

运行任何命令前，先确认容器状态：

```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

**期望看到 6 个容器**：`quant-data-router` + `hermes-hypothesis` + `hermes-data` + `hermes-quant` + `hermes-risk` + `hermes-writer`

- **容器不全** → 执行启动命令
- **全部在线** → 继续执行用户请求

## 启动 / 停止

### 启动整个系统
```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
bash launch.sh
```

等 10-15 秒后验证：
```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

### 健康检查（推荐启动后执行）
```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
python3 -m orchestrator.cli health
```

### 停止
```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
bash stop.sh
```

## 运行 Pipeline（核心操作）

### 完整跑一个研究主题
```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
python3 -m orchestrator.cli run --topic "你的研究主题"
```

**示例**：
```bash
python3 -m orchestrator.cli run --topic "动量与反转的边界条件"
```

**预估运行时间**（基于实际运行经验，每个 Agent 120 分钟超时）：

| Stage | 典型耗时 | 说明 |
|-------|---------|------|
| hypothesis | 10-20 min | 文献调研 + 假设生成 |
| data_engineer | 25-35 min | 数据获取 + 特征工程（可能初期卡代码） |
| quant_analyst | 20-30 min | 回测建模 + 多策略对比（可能因 LLM 流超时） |
| risk_auditor | 10-15 min | 过拟合检验 + GO/NO-GO 裁决 |
| strategy_writer | 5-10 min | 策略撰写或失败分析 |
| **总计** | **~70-110 min** | 建议预留 **2 小时** 完整运行 |

> ⚠️ **quant_analyst 最容易超时**：流式 LLM 响应可能因网络不稳定中断。如果发生，产出文件已写入磁盘，使用 `--from-stage` 中继恢复即可。

### Dry-Run（不调用 Agent，验证流程连通性）
```bash
python3 -m orchestrator.cli run --topic "测试" --dry-run
```
> 💡 **最佳实践**：首次运行新主题前，先 dry-run 验证所有容器健康。

### 从中间 stage 恢复（跳过已完成的阶段）
```bash
# 假设 hypothesis 和 data_engineer 已完成，从 quant_analyst 开始
python3 -m orchestrator.cli run --topic "动量与反转的边界条件" --from-stage quant_analyst
```
> ✅ 实际验证有效：quant_analyst 超时后，用 `--from-stage risk_auditor` 成功完成后续阶段。

### 跳过归档（保留 workspace 所有文件）
```bash
python3 -m orchestrator.cli run --topic "xxx" --skip-archive
```
> ⚠️ **副作用**：`--skip-archive` 会**同时跳过 HTML 报告生成**。如需 HTML，pipeline 完成后手动执行：
> ```bash
> python3 -c "from orchestrator.core.orchestrator import _archive_and_cleanup_run; from orchestrator.core.html_reporter import generate_html_report; from orchestrator.core.dag import WORKSPACE_ROOT; from pathlib import Path; run_id='run_xxx'; _archive_and_cleanup_run(run_id, 'topic'); generate_html_report(run_id, 'topic', WORKSPACE_ROOT, WORKSPACE_ROOT/'archive')"
> ```

### 启用流式输出（实时看 Agent 输出）
```bash
python3 -m orchestrator.cli run --topic "xxx" --stream
```

## Pipeline 产物

Pipeline 完成后自动：
1. **归档**：有价值的报告 + 图表保存到 `shared_workspace/archive/{run_id}/`
2. **清理**：中间数据（parquet、csv、raw JSON）从 workspace 删除释放磁盘
3. **HTML 报告**：自动生成 `shared_workspace/archive/{run_id}/final_report.html`

每个 Agent 产出**中英双语**报告（`{name}.md` + `{name}_en.md`）。

## 查看历史 Run

```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
python3 -m orchestrator.cli status
```

## 手动清理 Workspace

```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
python3 -m orchestrator.cli clear
```

> ⚠️ 这会删除 workspace 中所有文件（不包括 archive/），新 run 开始时会自动执行。

### 环境变量检查

`.env` 文件中的变量不会自动加载到当前 shell。启动前确保执行：
```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster
export $(grep -v '^#' .env | xargs)
```

### WebBridge 客户端

WebBridge 客户端脚本位于 `tools/webbridge_client.py`，通过 Docker volume 挂载到所有 Hermes 容器的 `/workspace/tools/webbridge_client.py`。

Agent SOUL.md 中调用方式：
```bash
python3 /workspace/tools/webbridge_client.py fetch --url "<URL>" --session <SESSION>
```

**已知问题**：旧版脚本硬编码端口 `8765`，正确端口为 `10086`（由 `WEBBRIDGE_PORT` 环境变量控制）。如遇连接失败，先检查 WebBridge 端口：
```bash
lsof -i :10086   # 应显示 kimi-webbridge 进程
```

## 故障排除

### 容器无法启动
```bash
# 查看日志
docker logs quant-data-router
docker logs hermes-hypothesis

# 重启单个容器
docker restart hermes-hypothesis
```

### Agent 健康检查失败
```bash
# 检查端口是否被占用
lsof -i :8642
curl http://localhost:8642/health
```

### data_router 数据获取慢
- data_router 有 SQLite cache（`./data_router/cache/data_cache.db`），已配置 Docker volume 持久化
- 同一 symbol/barSize/duration 的重复请求直接命中 cache，第二次几乎瞬时返回
- 如果 cache 被清空（容器重建），第一次请求需要走 IBKR，会比较慢

### Pipeline 某个 stage 返回 502

如果 orchestrator 调用 Agent 时返回 `openai.InternalServerError: Error code: 502`，可能原因：

1. **Hermes Agent 内部的 LLM API key 丢失** — 常见于流式传输重连后。重启对应 Agent 容器：
   ```bash
   docker restart hermes-hypothesis
   ```
2. **Kimi Code API 连接不稳定** — `Stream drop` + `RemoteProtocolError`。通常是暂时的，重试即可。
3. **请求处理超时** — 每个 Agent 超时为 **120 分钟**（已修改 `orchestrator/core/orchestrator.py` 中 `AGENT_TIMEOUTS`）。如果仍不够，可继续增加。

### Pipeline 某个 stage 超时（最常见：quant_analyst）

**症状**：orchestrator 日志停留在 `Calling quant_analyst @ localhost:8644 ...` 很久，最终后台任务 60-120 分钟超时。

**原因**：quant_analyst 的 LLM 流式传输可能因网络不稳定中断，但 Agent 内部已写完文件。

**解决**：
1. 检查 `shared_workspace/03_backtest/` 是否已有产出文件
2. 如果有文件，使用 `--from-stage risk_auditor` 中继恢复
3. 如果没有文件，检查 quant_analyst 容器日志：`docker logs hermes-quant`

### 后台任务总超时 vs Agent 超时

两个不同的超时层级：

| 超时类型 | 位置 | 默认值 | 控制方式 |
|----------|------|--------|----------|
| **后台任务总超时** | Shell 启动参数 | 60 min | 启动时 `timeout` 参数 |
| **单个 Agent 超时** | `AGENT_TIMEOUTS` | 120 min | 修改 `orchestrator/core/orchestrator.py` |
| **HTTP 连接超时** | `hermes.py` | 1800s | 修改 `orchestrator/clients/hermes.py` |

如果 Agent 产出已写入磁盘但 HTTP 响应未返回，增加 `AGENT_TIMEOUTS` 即可。

### Pipeline 某个 stage 失败
```bash
# 从失败 stage 恢复（自动跳过已完成的）
python3 -m orchestrator.cli run --topic "相同主题" --from-stage {失败的stage名}
```

### HTML 报告生成失败
- 检查 `shared_workspace/archive/{run_id}/` 是否存在
- 检查 `jinja2` 和 `markdown` 是否已安装：`pip3 install jinja2 markdown`

## 关键文件位置

| 文件 | 路径 | 说明 |
|------|------|------|
| 编排器 CLI | `orchestrator/cli.py` | CLI 入口（`python3 -m orchestrator.cli`） |
| WebBridge 客户端 | `tools/webbridge_client.py` | 挂载到容器 `/workspace/tools/` |
| 核心编排 | `orchestrator/core/orchestrator.py` | Pipeline 执行逻辑 |
| Agent DAG | `orchestrator/core/dag.py` | Agent 注册、依赖、输出文件 |
| HTML Reporter | `orchestrator/core/html_reporter.py` | 报告生成器 |
| Data Router | `data_router/` | IB Gateway REST 网关 |
| Agent 配置 | `agent_configs/{agent}/SOUL.md` | 每个 Agent 的指令 |
| Agent 配置 | `agent_configs/{agent}/config.yaml` | Hermes 运行时配置 |
| 产物目录 | `shared_workspace/` | 当前 run 的工作区 |
| 归档目录 | `shared_workspace/archive/` | 历史 run 的归档 |
| Docker 编排 | `docker-compose.yml` | 8 个服务定义 |

## 可复现性：为什么上次能跑通、这次不行？

这是 Quant Cluster 最常见的工程化痛点。根本原因：**系统没有实现"纯净启动"**。

### 状态泄漏全景图

```
对话 1（成功）          →  对话 2（失败）
state.db 全新            →  state.db 有旧记忆 → agent 决策偏离
kanban.db 全新           →  kanban.db 混乱 → no such table
cache 全新               →  cache 命中 stale 数据 → 回测不一致
workspace 空             →  workspace 有旧 .parquet → 误判上游已完成
```

### 正确的启动流程（每次 run 前必做）

```bash
cd /Users/yihaoyang/VScode\ workspace/quant-cluster

# 方法 A：一键纯净启动（推荐）
bash launch.sh --clean

# 方法 B：手动分步
bash reset.sh      # 清除所有跨 run 状态
bash launch.sh     # 启动容器
bash scripts/smoke_test.sh   # 验证纯净状态
```

### `launch.sh --clean` 做了什么？

1. 停止所有容器
2. 删除所有 Agent 的 `state.db` / `kanban.db` / `auth.lock`
3. 删除 Data Router 缓存
4. 清空 Workspace（保留 archive/）
5. 删除 Redis Volume
6. 删除 Orchestrator 本地 DB
7. 重新创建容器（`--force-recreate`）

### 永远不要做的事情

- ❌ 直接 `bash launch.sh`（不清除状态，等于"唤醒脏系统"）
- ❌ `git add .` 把 `orchestrator.db` 或 `agent_configs/*/*.db` 提交到仓库
- ❌ 手动删除 `shared_workspace/archive/`（唯一历史备份）

## 最优运行实例（Best Practices）

基于多次实际运行验证的**推荐流程**：

### 1. 启动前：一键纯净启动
```bash
bash launch.sh --clean   # 清除所有跨 run 状态，避免状态泄漏
bash scripts/smoke_test.sh   # 验证连通性
```

### 2. 首次运行新主题：先 dry-run
```bash
python3 -m orchestrator.cli run --topic "你的主题" --dry-run
```

### 3. 正式运行：后台任务 + 充足超时
```bash
# 在后台运行，总超时设为 3-4 小时
python3 -m orchestrator.cli run --topic "你的主题" --skip-archive
```
> `--skip-archive` 保留 workspace 文件便于调试。如需 HTML，结束后手动生成。

### 4. 监控：定期检查文件产出
```bash
# 每 10 分钟检查一次产出进度
watch -n 600 'ls -la shared_workspace/*/ | tail -20'
```

### 5. 超时恢复：`--from-stage` 中继
如果某个 stage 超时，不要从头重跑。检查已产出文件后从中继：
```bash
python3 -m orchestrator.cli run --topic "相同主题" --from-stage {下一个stage}
```

### 6. 运行质量检查清单

| 检查项 | 通过标准 |
|--------|---------|
| hypothesis 引用 | 无编造 arXiv ID/DOI；≥60% 近5年；所有引用 `text_chars >= 100` |
| data_engineer 数据量 | 实际缓存 < 100MB（非 TB 级理论估算） |
| quant_analyst 策略数 | ≥3 种策略对比，有参数热力图 |
| risk_auditor 结论 | 有明确的 GO/NO-GO 裁决，附统计检验 |
| strategy_writer | 根据审计结论写策略报告或失败分析，不强行包装 |

### 已验证的成功模式

- **data_engineer 降级策略**：当 tick 数据不可用时，诚实降级到 daily/hourly，用代码生成合成高频特征
- **quant_analyst 多策略对比**：同时测试 6+ 种策略变体，用参数热力图识别最优
- **risk_auditor 严格标准**：PBO < 0.50、参数稳定性 CV < 1.0、排列检验 p < 0.05
- **strategy_writer 诚实**：NO-GO 时写失败分析而非强行包装，附改进建议和重新审计清单

## Memory 管理（Pipeline 完成后执行）

每次 pipeline 成功完成后，提取关键发现写入长期记忆，供后续 run 自动 recall。

### 提取流程

1. 定位最新 archive：
   ```bash
   ls -t shared_workspace/archive/ | head -1
   ```

2. **优先读取 run_card.json**（结构化数据）：
   ```bash
   cat shared_workspace/archive/{run_id}/03_backtest/run_card.json
   ```
   关注字段：`metrics`（Sharpe、最大回撤等）、`backtest.engine`、`data_sources`、`warnings`。

3. **补充阅读定性报告**：
   - `01_hypothesis/hypothesis_*.md` → 核心假设
   - `04_risk/go_no_go_verdict.md` → 审计结论
   - `05_strategy/trading_sop_*.md` 或 `strategy_failure_analysis.md` → 最终结果

4. 生成 memory content（浓缩洞察，非全量报告）：
   ```markdown
   ## 核心假设
   - ...

   ## 关键发现
   - GO/NO-GO 结论 + 核心指标（来自 run_card）
   - ...

   ## 失败教训
   - ...（如有 warnings 或 NO-GO）

   ## 工具备注
   - backtest_engine: ...
   - data_source: ...
   - run_card_config_hash: ...
   ```

5. 写入记忆：
   ```bash
   python3 -m memory add \
       --name "{topic_slug}" \
       --content "$(cat memory_content.md)" \
       --type project \
       --description "一句话摘要（包含核心指标）"
   ```

6. 验证：
   ```bash
   python3 -m memory search "{topic_keyword}"
   ```

### 查询历史记忆

```bash
# 关键词搜索
python3 -m memory search "动量" --max-results 5

# 列出全部
python3 -m memory list

# 查看单条
python3 -m memory show "动量与反转的边界条件"
```

### 注意事项

- Memory 存储在 `~/.quant-cluster/memory/`（用户级），跨项目共享
- 同名主题会**覆盖更新**，不会生成重复文件
- description 字段用于检索评分（metadata 权重 2.0），务必写清楚核心结论
- CJK 搜索按字符级匹配，写关键词时无需考虑分词

## 全局约束

1. **永远不要手动删除 `shared_workspace/archive/` 中的内容** — 这是唯一的历史产物备份
2. **Data Router 是唯一连接 IB Gateway 的组件** — Agent 只能通过 `http://data-router:8888` 获取数据
3. **双语报告**：每个 Agent 的 SOUL.md 已要求产出 `_zh.md` + `_en.md`，HTML 报告会自动渲染双语切换标签页
4. **归档安全**：空 workspace 或归档失败时自动跳过清理，防止误删数据
