# Hypothesis Agent 重构设计规格

> 将 monolithic Hypothesis Agent 拆分为 Paper Scanner（论文处理器）与 Factor Explorer（因子库探索引擎），引入防彩票化工程纪律。

## 1. 背景与目标

### 1.1 当前问题

现有 Hypothesis Agent 一人包揽「搜论文 → 读论文 → 提取假设 → 关联因子 → 生成报告」。存在以下问题：

- **论文处理与因子探索耦合**：Agent 随机读论文后自制新因子，缺乏系统性
- **缺乏防彩票化机制**：无多重比较校正、无快速筛选、无极端行情压力测试
- **反馈循环慢**：假设不成立时仍需等待完整 pipeline 跑完才能发现

### 1.2 设计目标

- 将论文扫描与因子探索解耦为两个独立 Agent
- Paper Scanner 成为持续运行的知识收集服务
- Factor Explorer 成为交互式假设验证工具（人驱动）
- 在探索阶段就筛掉伪因子，减少 pipeline 浪费

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Paper Scanner（独立服务）                            │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────┐   │
│  │ 本地论文文件夹│────▶│  论文池      │────▶│ 人审阅（MD + HTML 卡片） │   │
│  │ PDF/HTML/MD  │     │ Papers/      │     │ 按可信度评分过滤         │   │
│  └──────────────┘     └──────────────┘     └──────────────────────────┘   │
│         │                                              │                     │
│         │                                              │ 人提出假设           │
│         │                                              ▼                     │
│         │                                   ┌──────────────────────────┐   │
│         │                                   │  Factor Explorer         │   │
│         │                                   │  （按需触发，交互式）      │   │
│         │                                   │  假设 → 因子库探索        │   │
│         │                                   └──────────────────────────┘   │
│         │                                               │                    │
│         │         Quick Death Test 通过 ▼               │ 未通过 = 丢弃      │
│         │                                   ┌──────────────────────────┐   │
│         │                                   │  假设审计（5道题）        │   │
│         │                                   │  多重比较校正             │   │
│         │                                   │  经济学解释               │   │
│         │                                   └──────────────────────────┘   │
│         │                                               │                    │
│         │                                               ▼ 人终审             │
│         │                                   ┌──────────────────────────┐   │
│         │                                   │  触发完整 Pipeline        │   │
│         │                                   │  （通过 Skill 封装）      │   │
│         │                                   └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Paper Scanner Agent

### 3.1 职责

持续扫描本地论文文件夹，产出结构化、经过方法论审计的论文卡片。

### 3.2 输入

- 本地论文文件夹路径（如 `~/papers/`），包含用户下载的 **PDF / HTML / TXT / MD**
- 可选：扫描范围过滤（日期、关键词、子文件夹）

### 3.3 处理流水线

| 阶段 | 执行者 | 产出 | 说明 |
|------|--------|------|------|
| **S1-文档解析** | Agent | 纯文本 + 结构化元数据 | 使用 pdfplumber / BeautifulSoup / markdown 解析 |
| **S2-方法论审计** | Agent（可访问网络） | 可信度评分（0-100） | 基于提取的元数据做程序化审计，网络用于验证 arXiv ID、DOI、作者 |
| **S3-结构化摘要** | Agent | 双格式卡片（MD + HTML） | MD 供 Agent 消费，HTML 供人阅读 |
| **S4-入池** | Agent | 存入 `shared_workspace/papers/` | 更新全局索引 |

### 3.4 方法论可信度评分

| 检查项 | 权重 | 审计方法 |
|--------|------|----------|
| 样本区间 >= 10 年 | +20 | 提取论文中的 data period 字段 |
| 明确样本外测试 | +20 | 检测关键词：out-of-sample, walk-forward, held-out |
| 包含交易成本/滑点 | +15 | 检测关键词：transaction cost, slippage |
| 无未来信息泄露 | +15 | 检测方法论中的 look-ahead bias 防护措施 |
| 数据可获取 | +15 | 检测是否使用独家/天价数据（卫星、暗网交易等） |
| 有经济学解释 | +15 | 检测是否引用行为金融学/市场微观结构理论 |

**评分分级**：
- `>= 60`：绿色，优先入池
- `40-59`：黄色，入池但标记警告
- `< 40`：红色，直接丢弃不入池

### 3.5 可迁移性评估

针对**美股 + ETF + 期权**交易场景的通用适配度：

| 维度 | 评估内容 |
|------|----------|
| 标的池兼容 | 论文中的因子是否适用于美股/ETF/期权？ |
| 数据频率兼容 | 日频？小时线？是否适配 IBKR 可提供的数据 |
| 交易成本敏感 | 高频因子在含摩擦后是否仍有效 |
| 期权适配 | 因子是否可用于隐含波动率曲面/期权定价 |

### 3.6 论文卡片格式

**`{source_slug}_{doc_id}_card.md`**（Agent 可读）

```markdown
---
doc_id: ssrn_4801234
title: "Momentum in Technology Stocks"
authors: ["John Doe", "Jane Smith"]
year: 2024
source: ssrn
credibility_score: 72/100
credibility_breakdown:
  sample_length: 20/20
  out_of_sample: 20/20
  transaction_costs: 10/15
  no_lookahead: 12/15
  data_accessible: 15/15
  economics_rationale: 15/15
---

## 核心假设
## 因子公式
## 数据集与回测区间
## 关键发现
## 方法论风险
## 可迁移性评估（美股+ETF+期权）
```

**`{source_slug}_{doc_id}_card.html`**（人可读）

- 美观排版，顶部大字显示可信度评分（带颜色标记）
- 可折叠的详细审计报告
- 人可以在浏览器中直接阅读

### 3.7 Workspace 结构

```
shared_workspace/
└── papers/
    ├── index.json                              # 全局索引，按可信度排序
    └── {source_slug}_{doc_id}/
        ├── {doc_id}_card.md
        ├── {doc_id}_card.html
        └── {doc_id}_full_text.txt              # 缓存全文（可选）
```

### 3.8 触发方式

- **定时触发**：通过 cron 或系统定时任务，扫描论文文件夹增量更新
- **手动触发**：人通过 CLI / 接口手动触发扫描

---

## 4. Factor Explorer Agent

### 4.1 职责

接收人提出的假设，在已有因子库中系统性探索参数空间、组合交互、Regime 适配，产出经过快速筛选和假设审计的终审报告。

### 4.2 输入

- 人的假设描述（自然语言，如「动量因子在 VIX<20 环境下对美股科技股是否有效」）
- 可选：论文池中的相关论文卡片（作为上下文增强）
- 可选：具体因子族限制（如「只在 alpha101 中探索」）

### 4.3 工作流程

```
假设解析（自然语言 → 因子查询计划）
    ↓
因子空间探索
    ├── 参数扫描：回看周期、计算方式、标准化方法
    ├── 组合交互：双因子/三因子条件交互
    └── Regime 识别：VIX/利率/信用利差环境下的有效性
    ↓
快速死亡测试（Quick Death Test）—— 封装为独立 Tool
    ├── 2020年2-3月（疫情崩盘）
    ├── 2021年11月-2022年10月（科技股熊市）
    └── 2018年2月（Volmageddon）
    └── 阈值：回撤 > 20% → 标记「彩票型因子」
    ↓
假设审计（5道题，自动回答）
    ↓
多重比较校正（Bonferroni / FDR）
    ↓
产出终审报告
```

### 4.4 Quick Death Test Tool

封装为独立 tool，方便 Factor Explorer 及其他 Agent / 人快速调用。

**接口**：

```python
def quick_death_test(
    factor_signal: pd.Series,      # 因子信号序列
    returns: pd.Series,             # 标的收益序列
    position_sizing: str = "equal", # 等权 / 波动率加权 / 信号强度
    threshold_drawdown: float = 0.20,
    windows: list[str] = ["2020-02:2020-04", "2021-11:2022-10", "2018-02:2018-03"]
) -> dict:
    """
    返回每个极端窗口的测试结果：
    {
        "2020_03_crash": {"max_drawdown": 0.15, "status": "PASS"},
        "2022_tech_bear": {"max_drawdown": 0.12, "status": "PASS"},
        "2018_volmageddon": {"max_drawdown": 0.22, "status": "FAIL"},
        "overall": "FAIL"  # 任一窗口 FAIL 则 overall FAIL
    }
    """
```

**设计原则**：
- 分钟级测试（使用预计算的因子值和收益数据）
- 在探索阶段就筛掉「顺境中奖、逆境归零」的伪因子
- 不替代完整 Walk-forward 回测，而是前置筛选

### 4.5 假设审计（5道题）

Factor Explorer 产出终审报告时，必须自动回答以下 5 道题，写入 `hypothesis_audit.md`：

| # | 问题 | 审计目的 |
|---|------|----------|
| 1 | 这个因子有效的经济学机制是什么？ | 确保有行为/摩擦/信息论基础，非纯数据挖掘 |
| 2 | 如果未来6个月失效，最可能的原因是什么？ | 预判失效模式（拥挤/Regime切换/数据质量） |
| 3 | 是否有可监控的「领先指标」能在失效前预警？ | 建立监控仪表盘信号 |
| 4 | 该因子与现有策略库中因子相关性多高？ | 避免重复造轮子 |
| 5 | 极端行情下该因子的表现如何？ | Quick Death Test 结果的解释性补充 |

### 4.6 多重比较校正

Factor Explorer 的产出必须包含校正后的统计结果：

- **Bonferroni 校正**：显著性阈值 = 0.05 / 测试次数
- **FDR 控制（Benjamini-Hochberg）**：控制假阳性因子比例
- **强制标注**：报告中必须显示「校正后 p 值」，未通过校正的因子组合不得标记为「显著」

### 4.7 输出文件

**`factor_exploration_report.json`**（结构化，供下游消费）

```json
{
  "hypothesis": "动量因子在 VIX<20 环境下对美股科技股有效",
  "exploration_id": "exp_20260528_001",
  "query_plan": {
    "factor_families": ["academic_carhart_mom", "alpha101_momentum"],
    "parameters_scanned": {
      "lookback": [5, 10, 20, 60],
      "weighting": ["simple", "vol_adjusted"]
    },
    "universe": "US_TECH_ETF"
  },
  "results": {
    "ic_matrix": {},
    "best_parameters": {
      "lookback": 20,
      "weighting": "vol_adjusted",
      "ic_mean": 0.052,
      "ir": 0.35
    },
    "regime_switches": {
      "vix_low": {"ic": 0.08},
      "vix_high": {"ic": -0.01}
    }
  },
  "quick_death_test": {
    "2020_03_crash": {"max_drawdown": 0.15, "status": "PASS"},
    "2022_tech_bear": {"max_drawdown": 0.12, "status": "PASS"},
    "2018_volmageddon": {"max_drawdown": 0.22, "status": "FAIL"}
  },
  "multiple_testing_correction": {
    "tests_run": 48,
    "bonferroni_threshold": 0.001,
    "significant_after_correction": true,
    "fdr_q_value": 0.03
  },
  "economics_rationale": "行为金融学：低波动环境下投资者过度外推动量...",
  "hypothesis_audit": {
    "q1_mechanism": "...",
    "q2_failure_mode": "...",
    "q3_early_warning": "...",
    "q4_correlation": "...",
    "q5_extreme_performance": "..."
  },
  "confidence": "medium"
}
```

**`factor_exploration_report.md`**（人可读，含探索结果摘要）

**`hypothesis_audit.md`**（人可读，5道题的详细回答）

### 4.8 触发决策点

Factor Explorer 产出终审报告后，人在以下选项中选择：

| 选项 | 行为 |
|------|------|
| **🟢 Approve** | 通过 Skill 触发完整 Pipeline |
| **🟡 Modify** | 修改假设，重新跑 Factor Explorer |
| **🔴 Reject** | 丢弃，不触发 |
| **⏸️ Hold** | 存入 `shared_workspace/candidate_hypotheses/` 候选池 |

---

## 5. Pipeline 触发 Skill

封装 Pipeline 触发逻辑为一个可复用 Skill：`trigger-pipeline`

### 5.1 职责

接收 Factor Explorer（或人）的指令，启动完整的 quant-cluster pipeline。

### 5.2 接口

```yaml
skill: trigger-pipeline
input:
  exploration_id: "exp_20260528_001"
  hypothesis: "动量因子在 VIX<20 环境下对美股科技股有效"
  source: "factor_explorer"  # 或 "manual"
  # 可选：覆盖默认 pipeline 配置
  pipeline_config:
    skip_risk: false
    backtest_years: [2015, 2024]
```

### 5.3 行为

1. 将 Factor Explorer 的 `factor_exploration_report.json` 复制到 `shared_workspace/01_hypothesis/`
2. 生成兼容格式的 `data_requirements.json`
3. 调用 orchestrator 启动 pipeline：`hypothesis → data_engineer → quant_analyst → risk_auditor → strategy_writer`

### 5.4 范围说明

- 本 Skill 只负责**触发**，不负责 pipeline 内部逻辑改造
- 下游 Agent 的接口扩展（消费 Factor Explorer 的丰富输出）**pending**，不在本次重构范围内

---

## 6. Agent 配置

### 6.1 Paper Scanner

```
agent_configs/paper_scanner/
├── SOUL.md
└── config.yaml
```

**SOUL.md 核心要点**：
- 角色：本地论文批量处理器 + 方法论审计员
- 输入：本地文件夹路径
- 输出：论文卡片（MD + HTML）+ 全局索引
- 工具：file（读写）、terminal（pdfplumber / BeautifulSoup）、web_search（验证元数据，≤5 次/任务）

### 6.2 Factor Explorer

```
agent_configs/factor_explorer/
├── SOUL.md
└── config.yaml
```

**SOUL.md 核心要点**：
- 角色：假设驱动的因子库探索引擎
- 输入：自然语言假设描述
- 输出：探索报告（JSON + MD）+ 假设审计（MD）
- 工具：file、terminal（调用因子库 / Quick Death Test）、memory（读取论文池）
- 强制纪律：
  - 每个候选组合必须附带经济学解释
  - 必须通过多重比较校正
  - 必须通过 Quick Death Test 才能进入假设审计

---

## 7. 防彩票化纪律汇总

| 防线 | 机制 | 实现位置 |
|------|------|----------|
| **先验约束** | 搜索空间被经济学逻辑裁剪 | Factor Explorer 假设解析器 |
| **方法论审计** | 论文可信度评分（0-100） | Paper Scanner S2 阶段 |
| **快速死亡测试** | 极端行情片段验证，回撤>20%丢弃 | Quick Death Test Tool |
| **假设审计** | 5 道题强制回答 | Factor Explorer 终审报告 |
| **多重比较校正** | Bonferroni + FDR | Factor Explorer 统计输出 |
| **样本外验证** | Walk-forward（由 quant_analyst 执行） | Pipeline 阶段（pending） |
| **拥挤度监控** | IC 滚动值 + 成交量异常 | 假设审计 Q3（pending 仪表盘） |

---

## 8. 实施范围与边界

### 8.1 在本次重构范围内

- [ ] Paper Scanner Agent（SOUL.md + config.yaml + 论文卡片模板）
- [ ] Factor Explorer Agent（SOUL.md + config.yaml + 探索报告模板）
- [ ] Quick Death Test Tool（独立封装）
- [ ] Pipeline 触发 Skill
- [ ] 论文池目录结构与全局索引格式
- [ ] `dag.py` 中新增 Agent 端口定义

### 8.2 明确排除（pending）

- [ ] 下游 data_engineer / quant_analyst / risk_auditor 的接口扩展
- [ ] 因子库本身的计算代码改造（Factor Explorer 调用现有因子库）
- [ ] 实时拥挤度监控仪表盘
- [ ] Walk-forward 回测引擎改造
- [ ] Paper Scanner 的网络爬取功能（本地源优先）

---

## 9. 文件清单

| 路径 | 类型 | 说明 |
|------|------|------|
| `agent_configs/paper_scanner/SOUL.md` | 新建 | Paper Scanner 系统提示 |
| `agent_configs/paper_scanner/config.yaml` | 新建 | Paper Scanner Hermes 配置 |
| `agent_configs/factor_explorer/SOUL.md` | 新建 | Factor Explorer 系统提示 |
| `agent_configs/factor_explorer/config.yaml` | 新建 | Factor Explorer Hermes 配置 |
| `tools/quick_death_test.py` | 新建 | Quick Death Test 独立工具 |
| `.kimi/skills/trigger-pipeline/SKILL.md` | 新建 | Pipeline 触发 Skill |
| `orchestrator/core/dag.py` | 修改 | 新增 Agent 端口定义 |
| `shared_workspace/papers/` | 新建目录 | 论文池根目录 |
| `shared_workspace/candidate_hypotheses/` | 新建目录 | 假设候选池 |

---

*设计日期：2026-05-28*
*状态：待审查*
