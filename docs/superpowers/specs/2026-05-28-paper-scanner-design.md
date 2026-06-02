# Paper Scanner Agent 设计规格

> 将 Hypothesis Agent 中的论文处理职责独立为持续运行的本地论文处理器，产出经过方法论审计的论文池。
> 配套设计：[Factor Explorer Agent 设计规格](2026-05-28-factor-explorer-design.md)

## 1. 背景与目标

### 1.1 当前问题

现有 Hypothesis Agent 一人包揽「搜论文 → 读论文 → 提取假设 → 关联因子 → 生成报告」。论文处理环节存在以下问题：

- **无方法论审计**：Agent 随机读论文，不对论文质量做系统性评估，容易被「回测漂亮但方法论垃圾」的论文误导
- **产出格式单一**：只有 Markdown，人阅读体验差
- **与因子探索耦合**：论文阅读和因子生成绑在一起，无法复用论文池

### 1.2 设计目标

- 成为独立的本地论文处理器，不绑定网络爬取
- 对每篇论文做自动化的方法论可信度评分
- 产出双格式卡片（MD 供 Agent 消费，HTML 供人阅读）
- 构建可持续复用的论文池，供 Factor Explorer 和人工审阅消费

### 1.3 与 Factor Explorer 的边界

| 维度 | Paper Scanner | Factor Explorer |
|------|--------------|-----------------|
| 触发方式 | 定时 / 手动 | 按需（人驱动） |
| 输入 | 本地论文文件（PDF/HTML/TXT/MD） | 自然语言假设描述 |
| 输出 | 论文卡片 + 论文池索引 | 因子探索报告 + 假设审计 |
| 是否访问网络 | 是（仅用于验证元数据） | 视需要（读取论文池等） |
| 与 Pipeline 关系 | 独立服务，不触发 Pipeline | 探索通过后触发 Pipeline |

Paper Scanner 的职责在「论文入池」处结束。Factor Explorer 从论文池中读取相关论文作为假设探索的上下文。

---

## 2. 架构位置

```
┌─────────────────────────────────────────────────────────────┐
│                    Paper Scanner（独立服务）                   │
│  ┌──────────────┐     ┌──────────────┐     ┌─────────────┐ │
│  │ 本地论文文件夹│────▶│  处理流水线   │────▶│   论文池     │ │
│  │ PDF/HTML/MD  │     │              │     │ Papers/     │ │
│  └──────────────┘     └──────────────┘     └─────────────┘ │
│                                                   │         │
│                          ┌────────────────────────┘         │
│                          ▼                                  │
│              ┌──────────────────────────┐                  │
│              │ 人审阅（MD + HTML 卡片）  │                  │
│              │ 按可信度评分过滤          │                  │
│              └──────────────────────────┘                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ 人提出假设时引用论文池
                              ▼
                    ┌──────────────────┐
                    │  Factor Explorer  │
                    │  （配套设计）      │
                    └──────────────────┘
```

---

## 3. 输入

- **主输入**：本地论文文件夹路径（如 `~/papers/`），包含用户下载的 **PDF / HTML / TXT / MD**
- **可选过滤**：
  - 日期范围（文件修改时间）
  - 关键词过滤（文件名或内容）
  - 子文件夹限定
- **增量模式**：仅处理新加入或修改过的论文，已处理的不重复扫描

---

## 4. 处理流水线

| 阶段 | 名称 | 执行者 | 产出 | 说明 |
|------|------|--------|------|------|
| S1 | 文档解析 | Agent | 纯文本 + 结构化元数据 | pdfplumber / BeautifulSoup / markdown 解析 |
| S2 | 元数据提取 | Agent | 标题、作者、年份、数据源、回测区间 | 从文本中抽取关键字段 |
| S3 | 方法论审计 | Agent（可访问网络） | 可信度评分（0-100） | 基于提取的元数据做程序化审计，网络仅用于验证 arXiv ID / DOI / 作者信息 |
| S4 | 可迁移性评估 | Agent | 美股+ETF+期权适配度 | 基于论文内容判断因子是否适用于目标交易场景 |
| S5 | 结构化摘要 | Agent | 双格式卡片（MD + HTML） | MD 供 Agent 消费，HTML 供人阅读 |
| S6 | 入池 | Agent | 存入论文池 + 更新索引 | 增量更新全局索引文件 |

### 4.1 S1-S2：文档解析与元数据提取

**支持的文件格式**：
- PDF：使用 `pdfplumber` 提取文本和表格
- HTML：使用 `BeautifulSoup` 提取正文
- TXT / MD：直接读取

**提取的元数据字段**：
- `title`：论文标题
- `authors`：作者列表
- `year`：发表年份
- `source`：来源标识（arXiv / SSRN / 用户标注等）
- `data_period`：论文中声称的数据区间
- `universe`：论文中使用的标的池
- `key_factors`：论文中涉及的核心因子
- `methodology_summary`：方法论一句话摘要

### 4.2 S3：方法论可信度评分

**评分维度与权重**：

| 检查项 | 权重 | 审计方法 |
|--------|------|----------|
| 样本区间 >= 10 年 | +20 | 提取 `data_period` 字段，计算跨度 |
| 明确样本外测试 | +20 | 检测关键词：out-of-sample, walk-forward, held-out, cross-validation |
| 包含交易成本/滑点 | +15 | 检测关键词：transaction cost, slippage, market impact, friction |
| 无未来信息泄露 | +15 | 检测方法论中是否提及 look-ahead bias 防护措施 |
| 数据可获取 | +15 | 检测是否使用独家/天价数据（卫星图像、暗网交易数据等） |
| 有经济学解释 | +15 | 检测是否引用行为金融学、市场微观结构、信息不对称等理论 |

**评分分级**：
- `>= 60`：**绿色**，优先入池，人优先阅读
- `40-59`：**黄色**，入池但标记警告，人需额外留意
- `< 40`：**红色**，方法论缺陷严重，直接丢弃不入池

**网络使用约束**：
- 每篇论文的网络验证（arXiv ID / DOI 校验）≤ 2 次
- 总网络调用每任务 ≤ 10 次

### 4.3 S4：可迁移性评估

针对**美股 + ETF + 期权**交易场景的通用适配度，非特定标的：

| 维度 | 评估问题 | 输出 |
|------|----------|------|
| 标的池兼容 | 论文中的因子是否适用于美股/ETF/期权？如 parking lot 车辆数对科技股不适用 | `compatible` / `partial` / `incompatible` |
| 数据频率兼容 | 日频？小时线？Tick？是否适配 IBKR 可提供的数据 | `daily` / `hourly` / `tick` / `unavailable` |
| 交易成本敏感 | 高频因子在含摩擦后是否仍有效 | `robust` / `sensitive` / `fragile` |
| 期权适配 | 因子是否可用于隐含波动率曲面/期权定价 | `applicable` / `partial` / `not_applicable` |

### 4.4 S5：结构化摘要

每篇论文产出两个文件：

#### MD 版本（Agent 消费）

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
transferability:
  universe_compat: "partial"    # 科技股适用，全市场需调整
  data_frequency: "daily"       # 日频，IBKR 可支持
  cost_sensitivity: "robust"    # 低频因子，对摩擦不敏感
  option_applicable: "partial"  # 可用于期权隐含波动率预测
---

## 核心假设
[一句话概括论文的核心交易假设]

## 因子公式
[论文中使用的核心因子公式，LaTeX 格式]

## 数据集与回测区间
- 数据区间：2010-01 至 2023-12
- 标的池：NASDAQ-100 成分股
- 频率：日频

## 关键发现
- 动量因子在科技股的 IC 均值为 0.05
- 经波动率调整后夏普提升至 1.2

## 方法论风险
- 未包含 2020 年 3 月极端行情
- 交易成本假设为 5bps，可能低估

## 可迁移性评估（美股+ETF+期权）
[详细说明适配度评估的理由]
```

#### HTML 版本（人阅读）

- 顶部大字显示可信度评分（带颜色标记：绿/黄/红）
- 可折叠的详细审计报告（点击展开每项的得分理由）
- 可迁移性评估的可视化展示
- 美观排版，支持在浏览器中直接打开

---

## 5. 论文池结构

```
shared_workspace/
└── papers/
    ├── index.json                              # 全局索引，按可信度排序
    │   # 格式见下方
    └── {source_slug}_{doc_id}/                 # 如 ssrn_4801234/
        ├── {doc_id}_card.md                    # Agent 可读卡片
        ├── {doc_id}_card.html                  # 人可读卡片
        └── {doc_id}_full_text.txt              # 缓存全文（可选）
```

### 5.1 全局索引 `index.json`

```json
{
  "last_updated": "2026-05-28T14:30:00Z",
  "total_papers": 127,
  "papers": [
    {
      "doc_id": "ssrn_4801234",
      "title": "Momentum in Technology Stocks",
      "authors": ["John Doe", "Jane Smith"],
      "year": 2024,
      "source": "ssrn",
      "credibility_score": 72,
      "credibility_tier": "green",
      "transferability_summary": {
        "universe_compat": "partial",
        "data_frequency": "daily",
        "cost_sensitivity": "robust",
        "option_applicable": "partial"
      },
      "key_factors": ["momentum", "volatility_adjustment"],
      "card_paths": {
        "md": "papers/ssrn_4801234/ssrn_4801234_card.md",
        "html": "papers/ssrn_4801234/ssrn_4801234_card.html"
      },
      "added_at": "2026-05-28T10:15:00Z"
    }
  ]
}
```

### 5.2 索引排序规则

1. 主排序：可信度评分降序（高可信度优先）
2. 次排序：年份降序（新论文优先）
3. 人可手动置顶或标记「已读/重要」

---

## 6. 触发方式

| 方式 | 说明 |
|------|------|
| **定时触发** | 通过系统 cron 或 orchestrator 定时任务，每天/每周扫描增量论文 |
| **手动触发** | 人通过 CLI 或接口手动触发，指定文件夹和过滤条件 |
| **批量触发** | 一次性处理整个文件夹（首次初始化时使用） |

---

## 7. 防彩票化贡献

Paper Scanner 作为防彩票化的第一道防线：

| 机制 | 作用 |
|------|------|
| 方法论可信度评分 | 在论文阶段就筛掉方法论垃圾，避免人浪费时间 |
| 可迁移性评估 | 避免将不适配目标交易场景的论文误认为有效 |
| 评分分级（绿/黄/红） | 给人明确的优先级信号，优先处理高质量论文 |

---

## 8. Agent 配置

### 8.1 目录结构

```
agent_configs/paper_scanner/
├── SOUL.md
└── config.yaml
```

### 8.2 SOUL.md 核心要点

- **角色**：本地论文批量处理器 + 方法论审计员
- **输入**：本地文件夹路径
- **输出**：论文卡片（MD + HTML）+ 全局索引 `index.json`
- **工具**：
  - `file`：读写论文卡片和索引
  - `terminal`：调用 pdfplumber / BeautifulSoup 解析文档
  - `web_search`：验证论文元数据（arXiv ID / DOI / 作者），**≤5 次/任务**
- **铁律**：
  - 不编造 arXiv ID 或 DOI
  - 未经验证的论文不得标记为「已验证」
  - 可信度评分必须逐项列出得分理由

### 8.3 config.yaml 要点

- 端口需与 `orchestrator/core/dag.py` 中的 `AGENTS` 定义一致（待定，需协调）
- `terminal.timeout` 建议 1800（PDF 解析可能耗时）

---

## 9. 与 Factor Explorer 的接口

Factor Explorer 通过以下方式消费论文池：

1. **读取 `index.json`**：获取论文列表，按可信度筛选
2. **读取 `{doc_id}_card.md`**：获取单篇论文的详细内容
3. **引用格式**：Factor Explorer 的报告中引用论文时，使用 `papers/{source_slug}_{doc_id}` 作为标识

Paper Scanner 保证：
- 论文池格式稳定，不因版本更新而破坏 Factor Explorer 的读取
- `index.json` 中始终包含 `card_paths` 字段，方便定位

---

## 10. 文件清单

| 路径 | 类型 | 说明 |
|------|------|------|
| `agent_configs/paper_scanner/SOUL.md` | 新建 | Paper Scanner 系统提示 |
| `agent_configs/paper_scanner/config.yaml` | 新建 | Paper Scanner Hermes 配置 |
| `shared_workspace/papers/index.json` | 新建 | 论文池全局索引 |
| `shared_workspace/papers/{doc_id}/` | 新建目录 | 论文卡片存储目录 |
| `orchestrator/core/dag.py` | 修改 | 新增 Paper Scanner Agent 端口定义 |

---

*设计日期：2026-05-28*
*配套设计：[Factor Explorer Agent 设计规格](2026-05-28-factor-explorer-design.md)*
*状态：待审查*
