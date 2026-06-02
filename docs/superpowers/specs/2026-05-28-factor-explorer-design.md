# Factor Explorer Agent 设计规格

> 将 Hypothesis Agent 中的因子探索职责独立为假设驱动的交互式探索引擎，内置防彩票化工程纪律。
> 配套设计：[Paper Scanner Agent 设计规格](2026-05-28-paper-scanner-design.md)

## 1. 背景与目标

### 1.1 当前问题

现有 Hypothesis Agent 在因子探索环节存在以下问题：

- **漫无目的的遍历**：Agent 随机读论文后自制新因子，在因子库中暴力搜索，缺乏先验约束
- **缺乏快速筛选**：没有极端行情压力测试，伪因子容易混入 pipeline
- **假设与审计脱节**：假设生成和假设审计之间没有明确的检查点
- **反馈循环慢**：假设不成立时仍需等待完整 pipeline 跑完才能发现

### 1.2 设计目标

- 成为**人驱动**的假设验证工具，接收自然语言假设后在因子库中系统性探索
- 在探索阶段就通过「快速死亡测试」筛掉伪因子
- 每个候选组合强制附带经济学解释和多重比较校正
- 产出包含假设审计的终审报告，人终审后才能触发 pipeline

### 1.3 与 Paper Scanner 的边界

| 维度 | Paper Scanner | Factor Explorer |
|------|--------------|-----------------|
| 触发方式 | 定时 / 手动 | 按需（人驱动） |
| 输入 | 本地论文文件（PDF/HTML/TXT/MD） | 自然语言假设描述 |
| 输出 | 论文卡片 + 论文池索引 | 因子探索报告 + 假设审计 |
| 是否访问网络 | 是（仅用于验证元数据） | 视需要（读取论文池等） |
| 与 Pipeline 关系 | 独立服务，不触发 Pipeline | 探索通过后触发 Pipeline |

Factor Explorer 从论文池中读取相关论文作为假设探索的上下文，但不对论文做处理。Paper Scanner 的职责在「论文入池」处结束。

---

## 2. 架构位置

```
┌─────────────────────────────────────────────────────────────┐
│                        人（驱动方）                           │
│         提出假设 ──▶ 审阅终审报告 ──▶ 触发 Pipeline          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Factor Explorer（按需触发）                 │
│  ┌──────────────┐                                          │
│  │ 假设解析      │ 自然语言 → 因子查询计划                   │
│  └──────────────┘                                          │
│         │                                                   │
│         ▼                                                   │
│  ┌──────────────┐                                          │
│  │ 因子空间探索  │ 参数扫描 / 组合交互 / Regime 识别         │
│  └──────────────┘                                          │
│         │                                                   │
│         ▼                                                   │
│  ┌──────────────────┐                                      │
│  │ Quick Death Test │ 极端行情片段验证（Tool 封装）          │
│  │ （独立 Tool）     │ 未通过 → 丢弃                          │
│  └──────────────────┘                                      │
│         │                                                   │
│         ▼                                                   │
│  ┌──────────────┐                                          │
│  │ 假设审计      │ 5道题自动回答                            │
│  └──────────────┘                                          │
│         │                                                   │
│         ▼                                                   │
│  ┌──────────────┐                                          │
│  │ 多重比较校正  │ Bonferroni / FDR                         │
│  └──────────────┘                                          │
│         │                                                   │
│         ▼                                                   │
│  ┌──────────────┐                                          │
│  │ 终审报告      │ JSON + MD + 假设审计                     │
│  └──────────────┘                                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ 人 Approve
┌─────────────────────────────────────────────────────────────┐
│              trigger-pipeline Skill                         │
│              启动完整 Pipeline                               │
│              hypothesis → data → quant → risk → strategy    │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 输入

### 3.1 主输入：假设描述

自然语言描述，例如：

- 「动量因子在 VIX<20 环境下对美股科技股是否有效」
- 「质量因子和价值因子的条件交互：高质量公司被低估时是否有额外 alpha」
- 「20日波动率调整动量在 QQQ 成分股上的参数稳健性」

### 3.2 可选输入

- **论文池上下文**：从 `shared_workspace/papers/index.json` 读取相关论文卡片，作为假设的理论支撑
- **因子族限制**：人可指定只在特定因子族中探索（如「只在 alpha101 中探索」）
- **参数约束**：人可指定参数搜索空间（如「回看周期只测 5/10/20/60 日」）

---

## 4. 工作流程

### 4.1 假设解析（自然语言 → 因子查询计划）

将人的自然语言假设转化为结构化的因子查询计划：

```json
{
  "hypothesis_text": "动量因子在 VIX<20 环境下对美股科技股有效",
  "query_plan": {
    "factor_families": ["academic_carhart_mom", "alpha101_momentum"],
    "parameters": {
      "lookback": [5, 10, 20, 60],
      "weighting": ["simple", "vol_adjusted", "industry_neutral"]
    },
    "universe": "US_TECH_ETF",
    "regime_filter": {"vix": {"operator": "<", "threshold": 20}},
    "combinations": {
      "max_order": 2,
      "interaction_types": ["conditioning", "multiplication"]
    }
  }
}
```

**解析规则**：
- 识别提到的因子族关键词（动量 → academic_carhart_mom / alpha101_momentum）
- 识别参数范围（如「5-60日」→ `[5, 10, 20, 60]`）
- 识别 Regime 条件（如「VIX<20」→ regime filter）
- 识别标的池（如「科技股」→ `US_TECH_ETF`）
- 若无法解析或假设与已知因子族无关，Agent 应拒绝并请求澄清

### 4.2 因子空间探索

基于查询计划，在因子库中系统性探索：

#### 参数扫描

对查询计划中指定的每个因子，扫描其参数空间：

| 扫描维度 | 示例 |
|----------|------|
| 回看周期 | 5, 10, 20, 60 日 |
| 计算方式 | 简单收益、对数收益、波动率调整收益 |
| 标准化方法 | z-score、排名分位数、行业中性化 |
| 加权方式 | 等权、市值加权、波动率倒数加权 |

产出：IC/IR 矩阵（参数 × 因子 × 标的池）

#### 组合交互

测试双因子/三因子的条件交互：

| 交互类型 | 示例 |
|----------|------|
| 条件交互 | 当 Quality 因子排名前 30% 时，Value 因子的预测力 |
| 乘法交互 | Momentum × Volatility（波动率调整动量） |
| 非线性交互 | 用决策树/浅层 NN 挖掘因子间非线性关系 |

**约束**：只测试有逻辑支撑的二元交互，拒绝暴力组合。

#### Regime 识别

分析因子在不同市场环境下的有效性：

| Regime 维度 | 条件示例 |
|-------------|----------|
| 波动率 | VIX < 20 / VIX > 30 |
| 利率环境 | 收益率曲线正/倒挂 |
| 信用利差 | IG 利差 < 100bps / > 200bps |
| 趋势强度 | 标普 200 日均线之上/下 |

产出：Regime × 因子的 IC 热力图

### 4.3 Quick Death Test（快速死亡测试）

封装为独立 Tool，在完整 Walk-forward 回测之前，先用极端行情片段快速验证因子的鲁棒性。

#### 极端行情窗口

| 窗口 ID | 时间段 | 事件 | 特征 |
|---------|--------|------|------|
| `2020_03_crash` | 2020-02 至 2020-04 | 疫情崩盘 | VIX 飙升至 80+，流动性危机 |
| `2022_tech_bear` | 2021-11 至 2022-10 | 科技股熊市 | NASDAQ 跌 35%+，加息周期 |
| `2018_volmageddon` | 2018-02 | Volmageddon | XIV 崩盘，量化因子集体踩踏 |

#### Tool 接口

```python
def quick_death_test(
    factor_signal: pd.Series,           # 因子信号序列（日期索引）
    returns: pd.DataFrame,              # 标的收益矩阵（日期 × 标的）
    position_sizing: str = "equal",     # 等权 / vol_weighted / signal_weighted
    threshold_drawdown: float = 0.20,   # 回撤阈值（默认 20%）
    windows: dict[str, tuple[str, str]] = {
        "2020_03_crash": ("2020-02-01", "2020-04-30"),
        "2022_tech_bear": ("2021-11-01", "2022-10-31"),
        "2018_volmageddon": ("2018-02-01", "2018-02-28"),
    }
) -> dict:
    """
    返回每个极端窗口的测试结果：
    {
        "2020_03_crash": {
            "max_drawdown": 0.15,
            "sharpe": -0.5,
            "status": "PASS"
        },
        "2022_tech_bear": {
            "max_drawdown": 0.12,
            "sharpe": 0.1,
            "status": "PASS"
        },
        "2018_volmageddon": {
            "max_drawdown": 0.22,
            "sharpe": -1.2,
            "status": "FAIL"
        },
        "overall": "FAIL"  # 任一窗口 FAIL 则 overall FAIL
    }
    """
```

#### 设计原则

- **分钟级测试**：使用预计算的因子值和收益数据，不需要完整回测引擎
- **前置筛选**：未通过 Quick Death Test 的因子组合直接丢弃，不进入假设审计
- **阈值可调**：人可调整 `threshold_drawdown`（默认 20%）
- **独立封装**：作为独立 Tool，可被 Factor Explorer、Quant Analyst 或人直接调用

### 4.4 假设审计（5道题）

Factor Explorer 产出终审报告时，必须自动回答以下 5 道题。这是防彩票化的核心机制。

| # | 问题 | 审计目的 | 输出要求 |
|---|------|----------|----------|
| 1 | 这个因子有效的经济学机制是什么？ | 确保有行为/摩擦/信息论基础，非纯数据挖掘 | 一句话经济学解释，引用具体理论 |
| 2 | 如果未来6个月失效，最可能的原因是什么？ | 预判失效模式 | 列出 1-3 个最可能的失效原因 |
| 3 | 是否有可监控的「领先指标」能在失效前预警？ | 建立监控仪表盘信号 | 具体指标 + 阈值 + 预警逻辑 |
| 4 | 该因子与现有策略库中因子相关性多高？ | 避免重复造轮子 | 相关系数 + 是否只是旧因子的变形 |
| 5 | 极端行情下该因子的表现如何？ | Quick Death Test 结果的解释性补充 | 引用 QDT 结果 + 分析原因 |

**过滤规则**：
- 第 1 题若无法给出合理经济学解释 → 直接标记「彩票型」，不进入候选
- 第 4 题若与现有因子相关性 > 0.85 → 标记「重复因子」，降低优先级

### 4.5 多重比较校正

Factor Explorer 的产出必须包含校正后的统计结果：

| 校正方法 | 说明 | 应用场景 |
|----------|------|----------|
| **Bonferroni 校正** | 显著性阈值 = 0.05 / 测试次数 | 保守场景，控制族错误率 |
| **FDR（Benjamini-Hochberg）** | 控制假阳性因子比例 | 平衡场景，允许一定假阳性 |

**强制标注要求**：
- 报告中必须显示「校正后 p 值」
- 必须标注「测试次数」（tests_run）
- 未通过校正的因子组合不得标记为「显著」
- 推荐在报告中增加一列「校正后显著性」供人快速判断

---

## 5. 输出文件

### 5.1 `factor_exploration_report.json`（结构化）

```json
{
  "exploration_id": "exp_20260528_001",
  "hypothesis_text": "动量因子在 VIX<20 环境下对美股科技股有效",
  "timestamp": "2026-05-28T14:30:00Z",
  "query_plan": {
    "factor_families": ["academic_carhart_mom", "alpha101_momentum"],
    "parameters_scanned": {
      "lookback": [5, 10, 20, 60],
      "weighting": ["simple", "vol_adjusted"]
    },
    "universe": "US_TECH_ETF",
    "regime_filter": {"vix": {"operator": "<", "threshold": 20}}
  },
  "results": {
    "ic_matrix": {
      "academic_carhart_mom_20d_simple": {"ic_mean": 0.052, "ir": 0.35},
      "academic_carhart_mom_20d_vol_adjusted": {"ic_mean": 0.068, "ir": 0.42}
    },
    "best_combination": {
      "factors": ["academic_carhart_mom_20d_vol_adjusted"],
      "ic_mean": 0.068,
      "ir": 0.42,
      "parameters": {"lookback": 20, "weighting": "vol_adjusted"}
    },
    "regime_analysis": {
      "vix_low": {"ic_mean": 0.08, "sample_ratio": 0.6},
      "vix_high": {"ic_mean": -0.01, "sample_ratio": 0.4}
    }
  },
  "quick_death_test": {
    "threshold": 0.20,
    "results": {
      "2020_03_crash": {"max_drawdown": 0.15, "sharpe": -0.5, "status": "PASS"},
      "2022_tech_bear": {"max_drawdown": 0.12, "sharpe": 0.1, "status": "PASS"},
      "2018_volmageddon": {"max_drawdown": 0.22, "sharpe": -1.2, "status": "FAIL"}
    },
    "overall": "FAIL"
  },
  "multiple_testing_correction": {
    "tests_run": 48,
    "bonferroni_threshold": 0.001,
    "fdr_q_value": 0.03,
    "significant_after_bonferroni": true,
    "significant_after_fdr": true
  },
  "economics_rationale": "行为金融学：低波动环境下投资者过度外推近期趋势，导致动量延续。参考 Jegadeesh & Titman (1993) 的动量效应理论。",
  "hypothesis_audit": {
    "q1_mechanism": "行为偏差：低波动环境下投资者风险厌恶降低，过度外推动量信号...",
    "q2_failure_mode": "1. VIX 持续>20 的 regime 切换；2. 动量因子拥挤度上升；3. 科技股流动性收紧",
    "q3_early_warning": "监控指标：VIX 20日均线突破20且维持5日以上；该因子暴露股票的成交量 20 日均值超过历史 90 分位数",
    "q4_correlation": "与现有 carhart_mom_20d 相关性 0.72，但 vol_adjusted 版本在 regime 开关下提供独立信息",
    "q5_extreme_performance": "2020-03 回撤15%（可控），2022-10 回撤12%（可控），2018-02 回撤22%（超出阈值，风险标记）"
  },
  "confidence": "medium",
  "recommendation": "conditional_go",
  "recommendation_reason": "Quick Death Test 在 2018-02 未通过，建议降低仓位上限或增加 regime 开关后再测试"
}
```

### 5.2 `factor_exploration_report.md`（人可读）

结构化摘要，包含：
- 假设描述和查询计划
- 最佳参数组合（高亮显示）
- IC/IR 矩阵（表格形式）
- Regime 分析（热力图文字描述）
- Quick Death Test 结果（绿/红标记）
- 多重比较校正结果
- 经济学解释
- 置信度和推荐行动

### 5.3 `hypothesis_audit.md`（假设审计报告）

```markdown
# 假设审计报告

## 探索 ID
exp_20260528_001

## 假设
动量因子在 VIX<20 环境下对美股科技股有效

---

## Q1: 经济学机制
**回答**：行为金融学：低波动环境下投资者过度外推近期趋势，导致动量延续。
**依据**：Jegadeesh & Titman (1993) 的动量效应理论；Hong & Stein (1999) 的渐进信息扩散模型。
**可信度**：高

## Q2: 失效原因预测
**最可能原因**：
1. VIX 持续>20 的 regime 切换（如 2020-03）
2. 动量因子拥挤度上升，alpha 被摊薄
3. 科技股流动性收紧，冲击成本放大

## Q3: 领先预警指标
| 指标 | 阈值 | 预警逻辑 |
|------|------|----------|
| VIX 20日均线 | > 20 维持 5 日 | Regime 切换，降低动量权重 |
| 因子暴露股成交量 20日均值 | > 历史 90 分位数 | 拥挤信号，准备撤退 |
| 因子 IC 滚动 30 日均值 | < 0 | 预测力消失，停用因子 |

## Q4: 与现有策略库相关性
- 与 `carhart_mom_20d` 相关性：0.72
- 与 `alpha101_001` 相关性：0.65
- **判断**：不是全新因子，但 vol_adjusted + regime 开关提供独立信息增量

## Q5: 极端行情表现
| 窗口 | 最大回撤 | 状态 | 分析 |
|------|----------|------|------|
| 2020-03 疫情崩盘 | 15% | ✅ PASS | 波动率飙升时 vol_adjusted 自动降仓 |
| 2022-10 科技股熊市 | 12% | ✅ PASS | 低波环境消失，但损失可控 |
| 2018-02 Volmageddon | 22% | ❌ FAIL | 量化因子集体踩踏，流动性冲击 |

**总体评估**：2018-02 未通过阈值，需增加流动性过滤条件或降低该因子仓位上限。

---

## 审计结论
- **推荐行动**：conditional_go（有条件通过）
- **条件**：增加流动性过滤（日均成交量 > $10M），或设置单因子仓位上限 15%
- **置信度**：medium
```

---

## 6. 触发决策与 Pipeline 启动

### 6.1 人审阅后的选项

Factor Explorer 产出终审报告后，人在以下选项中选择：

| 选项 | 行为 | 后续动作 |
|------|------|----------|
| **🟢 Approve** | 通过假设，触发 Pipeline | Factor Explorer 调用 `trigger-pipeline` Skill |
| **🟡 Modify** | 修改假设，重新探索 | 人提供修改后的假设，Factor Explorer 重新跑 |
| **🔴 Reject** | 丢弃 | 不触发任何动作，报告存入归档 |
| **⏸️ Hold** | 存入候选池 | 存入 `shared_workspace/candidate_hypotheses/` |

### 6.2 Pipeline 触发 Skill

封装 Pipeline 触发逻辑为可复用 Skill：`trigger-pipeline`

**Skill 接口**：

```yaml
skill: trigger-pipeline
input:
  exploration_id: "exp_20260528_001"
  hypothesis_text: "动量因子在 VIX<20 环境下对美股科技股有效"
  source: "factor_explorer"  # 或 "manual"
  report_path: "shared_workspace/candidate_hypotheses/exp_20260528_001/"
```

**Skill 行为**：
1. 读取 `factor_exploration_report.json`
2. 生成兼容格式的 `data_requirements.json`
3. 将探索报告复制到 `shared_workspace/01_hypothesis/`
4. 调用 orchestrator 启动 pipeline

---

## 7. 防彩票化纪律汇总

Factor Explorer 是防彩票化的核心执行层：

| 防线 | 机制 | 实现位置 |
|------|------|----------|
| **先验约束** | 搜索空间被经济学逻辑裁剪；拒绝无法映射到已知因子族的假设 | 假设解析器 |
| **快速死亡测试** | 极端行情片段验证，回撤>20%丢弃 | Quick Death Test Tool |
| **假设审计** | 5 道题强制回答；Q1 无经济学解释直接过滤 | 终审报告 |
| **多重比较校正** | Bonferroni + FDR；未通过校正不得标记显著 | 统计输出 |
| **相关性检查** | 与现有因子相关性>0.85 降低优先级 | 假设审计 Q4 |

---

## 8. Agent 配置

### 8.1 目录结构

```
agent_configs/factor_explorer/
├── SOUL.md
└── config.yaml
```

### 8.2 SOUL.md 核心要点

- **角色**：假设驱动的因子库探索引擎
- **输入**：自然语言假设描述
- **输出**：探索报告（JSON + MD）+ 假设审计（MD）
- **工具**：
  - `file`：读写报告和审计文件
  - `terminal`：调用因子库计算、Quick Death Test Tool
  - `memory`：读取论文池索引和卡片
- **铁律**：
  - 每个候选组合必须附带一句话经济学解释
  - 必须通过多重比较校正
  - 必须通过 Quick Death Test 才能进入假设审计
  - 假设审计 5 道题必须逐项回答，不得省略
  - 不得在未通过审计的情况下推荐触发 Pipeline

### 8.3 config.yaml 要点

- 端口需与 `orchestrator/core/dag.py` 中的 `AGENTS` 定义一致（待定，需协调）
- `terminal.timeout` 建议 1800（因子计算可能耗时）

---

## 9. 与 Paper Scanner 的接口

Factor Explorer 通过以下方式消费论文池：

1. **读取 `shared_workspace/papers/index.json`**：获取论文列表
2. **按可信度筛选**：优先读取 `credibility_score >= 60` 的论文
3. **读取 `{doc_id}_card.md`**：获取单篇论文的详细内容
4. **在报告中引用**：引用格式为 `papers/{source_slug}_{doc_id}`

Factor Explorer 对 Paper Scanner 的依赖：
- 论文池格式稳定（`index.json` 结构、卡片 frontmatter 字段）
- 论文池路径固定（`shared_workspace/papers/`）

---

## 10. 文件清单

| 路径 | 类型 | 说明 |
|------|------|------|
| `agent_configs/factor_explorer/SOUL.md` | 新建 | Factor Explorer 系统提示 |
| `agent_configs/factor_explorer/config.yaml` | 新建 | Factor Explorer Hermes 配置 |
| `tools/quick_death_test.py` | 新建 | Quick Death Test 独立工具 |
| `.kimi/skills/trigger-pipeline/SKILL.md` | 新建 | Pipeline 触发 Skill |
| `shared_workspace/candidate_hypotheses/` | 新建目录 | 假设候选池 |
| `orchestrator/core/dag.py` | 修改 | 新增 Factor Explorer Agent 端口定义 |

---

*设计日期：2026-05-28*
*配套设计：[Paper Scanner Agent 设计规格](2026-05-28-paper-scanner-design.md)*
*状态：待审查*
