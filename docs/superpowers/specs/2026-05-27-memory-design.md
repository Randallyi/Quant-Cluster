# Memory 系统设计文档

Date: 2026-05-27  
Status: Draft — pending implementation  
Inspired by: Vibe-Trading `agent/src/memory/persistent.py`

---

## 1. 背景与目标

### 现状痛点

- 每次 pipeline run 从零开始，Agent 之间无跨 run 记忆传递
- `shared_workspace/archive/` 有全量报告但无提取/索引/检索系统
- 同一主题多次研究时，Agent 重复犯相同错误或重新探索已知结论

### 设计目标

1. **跨 run 记忆沉淀**：pipeline 完成后，关键发现被提取并持久化
2. **Agent 自动 recall**：新 run 启动时，相关历史记忆自动注入 Agent context
3. **零外部依赖**：不引入 SQLite/FTS5/jieba/向量数据库，纯 Python 实现
4. **对齐 Vibe-Trading**：复用已验证的架构模式，降低设计风险

---

## 2. 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│  Pipeline Run                                               │
│  hypothesis → data_engineer → quant_analyst → ...           │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ (pipeline 完成后)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Kimi Code (via Skill)                                      │
│  ├── 读取 archive/{run_id}/03_backtest/run_card.json        │
│  ├── 读取各阶段 .md 报告                                     │
│  ├── 人工提炼洞察 → memory content                          │
│  └── python3 -m memory add --name ... --content ...         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  ~/.quant-cluster/memory/                                   │
│  ├── MEMORY.md           ← 自动维护索引（< 200 行）          │
│  └── project_{slug}.md   ← 主题记忆卡片（YAML frontmatter）  │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐      ┌─────────────────────────────┐
│  新 Pipeline 启动时     │      │  用户查询时                 │
│  Orchestrator._execute_ │      │  python3 -m memory search   │
│  agent() 注入 recall    │      │  "{query}"                  │
└─────────────────────────┘      └─────────────────────────────┘
```

---

## 3. 数据模型与存储格式

### 3.1 Memory Entry 文件

单文件 = 单主题记忆卡片，格式：YAML frontmatter + Markdown body。

```markdown
---
name: 动量与反转的边界条件
description: QQQ动量策略在2025年Q1失效，反转信号在波动率>20%时显著
type: project
---

## 核心假设
- 动量效应在波动率放大时减弱，反转效应增强
- 使用 20 日波动率作为状态切换指标

## 关键发现
- GO — 反转策略 Sharpe 1.8，最大回撤 12%
- 动量策略 Sharpe 0.3，在 VIX>20 期间连续亏损
- 数据：yfinance QQQ 日线 + VIX 指数

## 失败教训
- 无（本次为 GO）

## 工具备注
- backtest_engine: global_equity
- data_source: yfinance → ibkr fallback
- run_card_config_hash: a1b2c3...
```

### 3.2 索引文件（MEMORY.md）

自动维护，上限 200 行：

```markdown
- [动量与反转的边界条件](project_动量与反转的边界条件.md) — QQQ动量策略在2025年Q1失效，反转信号在波动率>20%时显著
- [机器学习因子实验](project_机器学习因子实验.md) — XGBoost因子在A股表现优于线性模型，但过拟合风险高
```

### 3.3 存储目录

```
~/.quant-cluster/memory/
├── MEMORY.md                      # 索引
└── project_动量与反转的边界条件.md  # 记忆卡片
```

- 用户级存储（非项目级），跨项目共享研究洞察
- 目录在 `PersistentMemory.__init__()` 中自动创建

---

## 4. Agent Recall 注入方式

### 4.1 注入点

`orchestrator/core/orchestrator.py` 的 `_execute_agent()` 方法：

```python
async def _execute_agent(self, agent_name, topic, run_id, stream, dry_run):
    system_prompt = _read_soul(agent_name)
    user_prompt = DAG[agent_name]["prompt_template"].format(topic=topic)
    
    # 新增：recall 相关记忆
    from memory.persistent import PersistentMemory
    mem = PersistentMemory()
    relevant = mem.find_relevant(topic, max_results=3)
    if relevant:
        memory_block = "\n\n".join([
            f"[历史研究记忆 #{i+1}]\n{e.title} — {e.description}\n{e.body[:500]}"
            for i, e in enumerate(relevant)
        ])
        system_prompt += (
            f"\n\n---\n"
            f"以下历史研究可能与当前任务相关，请避免重复已知错误、复用有效方法：\n"
            f"{memory_block}"
        )
    
    # 发送给 Agent...
```

### 4.2 注入策略

| 维度 | 决策 |
|------|------|
| 注入位置 | `system_prompt` 末尾（与 SOUL.md 融合） |
| 数量上限 | 最多 3 条相关记忆 |
| 内容截断 | 每条 body 最多 500 字符 |
| 相关性计算 | token 交集评分：metadata 权重 2.0 + body 权重 1.0 |

### 4.3 Agent SOUL.md 更新

每个 Agent 的 `SOUL.md` 中增加一段指令（追加到「角色定义」或「工作流」章节）：

```markdown
## 历史研究参考

启动时，如果上下文中有 [历史研究记忆] 区块，请：
1. 阅读相关记忆，理解之前同类研究的结论和教训
2. 避免重复已被证伪的假设或方法
3. 如记忆中有有效的数据/工具配置，优先复用
4. 在产出中明确说明「本研究与历史研究 X 的关系」（延续、修正、或无关）
```

---

## 5. 文件结构与模块划分

### 5.1 代码布局

```
quant-cluster/
├── memory/                      # ← 新增模块
│   ├── __init__.py              # 导出 PersistentMemory, MemoryEntry
│   ├── persistent.py            # 核心：存储、检索、索引
│   └── __main__.py              # CLI 入口
├── orchestrator/
│   └── core/
│       └── orchestrator.py      # 修改：_execute_agent() 注入 recall
├── agent_configs/               # 修改：5 个 SOUL.md 增加 recall 指令
│   ├── hypothesis/SOUL.md
│   ├── data_engineer/SOUL.md
│   ├── quant_analyst/SOUL.md
│   ├── risk_auditor/SOUL.md
│   └── strategy_writer/SOUL.md
└── .kimi/skills/
    └── quant-cluster/
        └── SKILL.md             # 修改：新增 Memory 提取章节
```

### 5.2 `memory/persistent.py` 核心类

对齐 Vibe-Trading `agent/src/memory/persistent.py`：

| 方法 | 职责 |
|------|------|
| `__init__(memory_dir)` | 初始化存储目录，加载 snapshot |
| `add(name, content, memory_type, description)` | 创建/更新记忆条目，自动维护索引 |
| `remove(name)` | 删除记忆条目 |
| `find(name)` | 精确匹配（标题 → 文件名 stem fallback） |
| `find_relevant(query, max_results)` | 关键词评分搜索 |
| `list_entries()` | 列出所有记忆 |
| `snapshot` (property) | MEMORY.md 前 200 行，用于 prompt 注入 |

### 5.3 Tokenization 策略

对齐 Vibe-Trading：

- ASCII 单词：≥3 字符，下划线视为分隔符（`snake_case` → `snake`, `case`）
- 非拉丁字符：CJK、Thai、Arabic、Hebrew、Cyrillic 按**单字**切分
- **无 jieba 分词**，字符级匹配对量化研究场景足够

### 5.4 CLI 接口

```bash
# 添加/更新记忆
python3 -m memory add \
    --name "动量与反转的边界条件" \
    --content "## 核心假设\n..." \
    --type project \
    --description "QQQ动量策略在2025年Q1失效"

# 搜索记忆
python3 -m memory search "动量" --max-results 5

# 列出所有记忆
python3 -m memory list

# 查看单条记忆
python3 -m memory show "动量与反转的边界条件"
```

---

## 6. Run Card 整合

### 6.1 为什么重要

`backtest/engines/run_card.py` 已移植到 Quant Cluster，生成 `run_card.json` + `run_card.md`。Run card 是 memory 提取的**结构化金矿**：

| Run Card 字段 | Memory 用途 |
|--------------|------------|
| `metrics.*` (sharpe, max_drawdown 等) | 直接填入「关键发现」的量化结论 |
| `backtest.engine` / `backtest.source` | 填入「工具备注」 |
| `data_sources` | 记录数据获取链路 |
| `reproducibility.config_hash` | memory 中引用可复现配置 |
| `warnings` | 映射到「失败教训」 |
| `validation` | 风控审计量化指标 |

### 6.2 Skill 提取流程

Pipeline 完成后，Kimi Code 执行：

```markdown
1. 定位最新 archive：`ls -t shared_workspace/archive/ | head -1`

2. 优先读取 run_card.json（结构化数据，无需 LLM 解析）：
   `cat shared_workspace/archive/{run_id}/03_backtest/run_card.json`

3. 补充阅读定性报告：
   - `01_hypothesis/hypothesis_*.md` → 核心假设
   - `04_risk/go_no_go_verdict.md` → 审计结论
   - `05_strategy/trading_sop_*.md` 或 `strategy_failure_analysis.md` → 最终结果

4. 生成 memory content：
   - 用 run_card.metrics 填充「关键发现」量化部分
   - 用报告填充「核心假设」和「失败教训」定性部分
   - 用 run_card.backtest/data_sources 填充「工具备注」

5. 写入记忆：`python3 -m memory add ...`
```

---

## 7. Skill 整合

### 7.1 quant-cluster Skill 更新

在 `/.kimi/skills/quant-cluster/SKILL.md` 中新增「Memory 管理」章节，包含：

1. **提取子流程**：pipeline 完成后必读文件清单（含 run_card.json）
2. **写入命令**：`python3 -m memory add ...` 的完整示例
3. **查询命令**：`python3 -m memory search/list/show` 用法
4. **recall 验证**：新 run 启动后检查 Agent 输出是否引用历史记忆

### 7.2 为什么不自动化提取

- Orchestrator Python 代码当前**无 LLM API 配置**，仅作为 Agent 调度器
- Memory 内容需要**质量判断**（哪些发现值得记住），当前由 Kimi Code 人工把关
- 未来如配置 LLM API key，可升级为自动提取，但基础设施（`persistent.py`）不变

---

## 8. 关键设计决策汇总

| 决策 | 选择 | 理由 |
|------|------|------|
| 提取方式 | Kimi Code 人工提取（via Skill） | Orchestrator 无 LLM API 配置 |
| 存储引擎 | 纯文件系统（Markdown + YAML frontmatter） | 对齐 Vibe-Trading，零依赖 |
| 搜索算法 | Python set 交集 + 权重评分 | 无 FTS5/SQLite，够用 |
| CJK 处理 | 字符级 tokenization | 对齐 Vibe-Trading，无 jieba |
| 更新策略 | 覆盖更新 | 对齐 Vibe-Trading，简单可靠 |
| 存储位置 | `~/.quant-cluster/memory/` | 用户级，跨项目共享 |
| 注入位置 | `system_prompt` 末尾 | 与 SOUL.md 融合，Agent 视为自身知识 |

---

## 9. 验收标准

| # | 验收项 | 验证方式 |
|---|--------|---------|
| 1 | `python3 -m memory add` 能创建/更新记忆卡片 | CLI 手动测试 |
| 2 | `python3 -m memory search "动量"` 返回相关记忆 | CLI 手动测试 |
| 3 | `python3 -m memory list` 显示所有记忆 | CLI 手动测试 |
| 4 | `~/.quant-cluster/memory/MEMORY.md` 自动维护 | 文件系统检查 |
| 5 | Pipeline 运行时 `_execute_agent()` 注入相关记忆 | 检查 Agent 输出是否引用历史研究 |
| 6 | CJK 搜索正常（「动量」匹配「动量策略」） | 搜索测试 |
| 7 | 同名主题覆盖更新，不生成重复文件 | 多次 add 同名记忆验证 |
| 8 | 5 个 Agent SOUL.md 增加 recall 指令 | 文件 diff |
| 9 | quant-cluster Skill 新增 Memory 章节 | 文件 diff |

---

## 10. 后续迭代方向

1. **自动提取**：Orchestrator 配置 LLM API key 后，在 `_archive_and_cleanup_run()` 后自动调用 LLM 生成 memory
2. **分层摘要**（方案 C）：同主题多次 run 时，保留历史区块 + 自动生成元摘要
3. **向量检索**：如记忆量 >100 条，可引入轻量级向量检索（如 `sentence-transformers` + `faiss`）
4. **跨用户共享**：项目级 memory + 导出/导入功能
