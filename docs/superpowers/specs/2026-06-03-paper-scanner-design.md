# Paper Scanner Skill 设计规格

> Paper Manager Agent 的论文扫描技能。将 `shared_workspace/papers/raw/` 中的 PDF 逐篇深度阅读，产出结构化论文卡片和全局索引，供人工审阅和 Factor Explorer 消费。
>
> 配套设计：[Factor Explorer Agent 设计规格](2026-05-28-factor-explorer-design.md)

---

## 1. 背景与目标

### 1.1 当前状态

论文下载环节已基本解决（`paper-downloading` skill），`shared_workspace/papers/raw/` 已累积大量来自多源的 PDF：

- **期刊源**（高影响力同行评审）：Elsevier、Wiley、CORE、NeurIPS、AISTATS
- **预印本源**（内容参差）：arXiv、SSRN

这些论文需要被系统性地阅读、理解和结构化，才能进入后续研究流程。

### 1.2 设计目标

- **研究员助手模式**：逐篇深度阅读论文，像人类研究员一样做笔记和分析
- **避免上下文污染**：每篇论文独立处理，论文之间不共享分析上下文
- **内容价值分层**：识别论文不同部分的价值密度，高价值部分精读，低价值部分跳过
- **所有论文都有价值**：非量化论文同样产出完整基础卡片（领域知识来源）
- **量化论文额外深度**：对实证量化论文做方法论审计、可迁移性评估、因子提取
- **可持续复用**：产出结构化卡片池，供 Factor Explorer 和人工审阅消费

### 1.3 与 Factor Explorer 的边界

| 维度 | Paper Scanner | Factor Explorer |
|------|--------------|-----------------|
| 触发方式 | 手动（初期限定） | 按需（人驱动） |
| 输入 | 本地 PDF 文件 | 自然语言假设描述 |
| 输出 | 论文卡片 + 索引 | 因子探索报告 + 假设审计 |
| 是否访问网络 | 否（纯本地处理） | 视需要 |
| 与 Pipeline 关系 | 独立 skill，不触发 Pipeline | 探索通过后触发 Pipeline |

Paper Scanner 的职责在「论文卡片入池」处结束。Factor Explorer 从卡片池中读取相关论文作为假设探索的上下文。

---

## 2. 架构位置

```
┌─────────────────────────────────────────────────────────────┐
│                  Paper Manager Agent (port 8647)             │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              paper-scanning Skill                     │   │
│  │                                                      │   │
│  │  父 Agent（调度者）                                   │   │
│  │  ├── 维护 scan_state.json（全局队列 & 状态）           │   │
│  │  ├── 调用脚本层做 PDF 智能分片                         │   │
│  │  ├── 按优先级调度 Subagent（有限并发）                 │   │
│  │  ├── 收集 Subagent 产出（结构化 JSON）                 │   │
│  │  ├── 组装标准 Markdown 卡片                           │   │
│  │  └── 更新 scanned/index.json                          │   │
│  │                                                      │   │
│  │  Subagent（论文理解专家）× max_concurrent             │   │
│  │  ├── 读 content_package.json（分片内容）               │   │
│  │  ├── 产出基础分析（所有论文）                          │   │
│  │  ├── 判断 paper_type（quantitative / 其他）            │   │
│  │  └── 产出量化深度分析（仅 quantitative）               │   │
│  │                                                      │   │
│  │  脚本层（确定性工具）                                  │   │
│  │  └── slice_pdf.py：PDF → 智能内容分片                 │   │
│  └──────────────────────────────────────────────────────┘   │
│                              │                               │
│                              ▼                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              shared_workspace/papers/                 │   │
│  │  ├── raw/{source}/...          # 原始 PDF（已有）      │   │
│  │  ├── scanned/                   # 扫描产出（新）        │   │
│  │  │   ├── index.json             # 全局索引              │   │
│  │  │   └── {doc_id}/              # 单篇论文卡片目录      │   │
│  │  │       ├── card.md            # 中文卡片              │   │
│  │  │       ├── card_en.md         # 英文精简卡片          │   │
│  │  │       ├── content_package.json # 分片内容缓存       │   │
│  │  │       └── figures/           # figure 图片提取       │   │
│  │  └── scan_state.json           # 扫描状态              │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 输入

### 3.1 主输入

`shared_workspace/papers/raw/` 下的 PDF 文件，按来源组织：

```
raw/
├── arxiv_qfin_tr/
├── arxiv_cs_lg/
├── ssrn/
├── elsevier/
├── wiley/
├── core_ac/
├── neurips_2025/
└── aistats_2025/
```

### 3.2 增量判断

扫描器通过 `scan_state.json` 判断哪些论文已处理、哪些未处理：

- `filepath` 不在 `scan_state.papers` 中 → 未扫描
- `status == "pending"` → 等待处理
- `status == "completed"` → 已处理，跳过

### 3.3 可选过滤

手动触发时可指定：
- 来源限定（如「只扫 Elsevier 的」）
- 年份范围
- 关键词过滤（文件名匹配）

---

## 4. 处理流水线

### 4.1 阶段总览

| 阶段 | 执行者 | 输入 | 输出 |
|------|--------|------|------|
| P1 | 脚本层 | PDF 文件 | `content_package.json`（分片内容） |
| P2 | 父 Agent | `content_package.json` | 启动 Subagent，传入分片 |
| P3 | Subagent | 分片内容 | 结构化分析 JSON |
| P4 | 父 Agent | 分析 JSON | `card.md` + `card_en.md` |
| P5 | 父 Agent | 卡片文件 | 更新 `scan_state.json` + `index.json` |

### 4.2 P1：PDF 智能内容分片（脚本层）

**目标**：像资深研究员一样「策展」论文内容，只提取高价值部分，丢弃低价值噪音。

**内容价值分层**：

| 层级 | 内容 | 处理方式 |
|------|------|----------|
| **Tier 1（核心骨架）** | title, abstract, **figures（数据配图/图表）**, figure captions, tables, intro, conclusions | **必提取**，所有论文都送 Agent |
| **Tier 2（数据/实证）** | data section, methodology, results, trading costs mentions | **条件提取**：检测到量化关键词时提取 |
| **Tier 3（证明/推导）** | appendix, proofs, derivations, mathematical details | **标记存在但不提取**：高价值论文才按需读取 |
| **丢弃** | references, related work, acknowledgments, literature review | 直接跳过 |

**分片脚本 `slice_pdf.py`**：

```python
def slice_pdf(filepath: str) -> dict:
    """
    将 PDF 智能分片为结构化内容包。
    
    使用 PyMuPDF (fitz) 提取文本 + 字体信息，
    启发式识别 section headers（字体大小、位置、关键词匹配）。
    
    降级策略：结构解析失败时，fallback 为全文纯文本提取，
    由 Subagent 自行做 section 分割。
    """
    doc = fitz.open(filepath)
    
    # 1. 提取所有文本块 + 字体元数据
    blocks = extract_text_blocks_with_fonts(doc)
    
    # 2. 启发式识别 section headers
    sections = identify_sections_by_heuristics(blocks)
    
    # 3. 按层级提取内容
    core_package = {
        "title": extract_title(blocks),
        "abstract": extract_section(sections, "abstract"),
        "intro": extract_section(sections, "introduction"),
        "conclusions": extract_section(sections, "conclusion"),
        "figures": extract_all_figures(doc),              # 提取为图片文件
        "figure_captions": extract_all_captions(sections, "figure"),
        "table_captions": extract_all_captions(sections, "table"),
        "tables": extract_structured_tables(doc),
    }
    
    # 4. 检测是否为量化实证论文
    quant_keywords = [
        "backtest", "portfolio", "factor", "alpha", "sharpe", "return",
        "empirical", "data", "sample", "transaction cost", "slippage",
        "momentum", "value", "volatility", "mean reversion"
    ]
    is_likely_quant = contains_keywords(blocks, quant_keywords, threshold=3)
    
    empirical_package = None
    if is_likely_quant:
        empirical_package = {
            "data_section": extract_section(sections, "data"),
            "methodology_section": extract_section(sections, "methodology", "empirical"),
            "results_section": extract_section(sections, "results"),
            "trading_costs": grep_keywords(blocks, ["transaction cost", "slippage", "market impact"]),
        }
    
    # 5. 标记证明/推导 section（不提取内容）
    proofs_package = {
        "available_sections": find_sections(sections, ["appendix", "proof", "derivation"]),
        "page_ranges": get_page_ranges(...),
        "extracted": False,
    }
    
    return {
        "doc_id": generate_doc_id(filepath),
        "filepath": filepath,
        "core": core_package,
        "empirical": empirical_package,
        "proofs": proofs_package,
        "is_likely_quant": is_likely_quant,
        "extraction_quality": "full" if sections else "fallback_text_only",
    }
```

**输出**：`content_package.json` 缓存到 `scanned/{doc_id}/content_package.json`

### 4.3 P2-P3：Subagent 逐篇深度分析

**并发策略**：
- `max_concurrent: 3`（默认，可配置）
- 父 Agent 维护运行中的 Subagent 列表，轮询收集结果
- 用户喊停时：不再启动新 Subagent，等待运行中的自然完成

**队列优先级**：

| 优先级 | 来源 | 理由 |
|--------|------|------|
| 1 | 期刊源（Elsevier/Wiley/CORE/NeurIPS/AISTATS） | 高影响力同行评审，默认高价值 |
| 2 | SSRN | 偏金融实务，质量参差但方向相关 |
| 3 | arXiv | 最宽泛，需 LLM 质量判断 |

同优先级内按 `year` 降序、再按 `added_at` 降序。

**Subagent 输入**：

```json
{
  "doc_id": "elsevier_10.1111_jofi.70040",
  "source_tier": "journal",
  "instructions": "你是一位量化研究论文分析专家。请逐篇阅读论文内容，产出结构化分析。",
  "todo": [
    "Step 1: 阅读 Core Package（title/abstract/intro/conclusions/figures/tables）",
    "Step 2: 判断 paper_type: quantitative / theoretical / review / empirical_non_quant / other",
    "Step 3: 产出基础分析（目标/贡献/方法/量化价值/引申阅读）",
    "Step 4: 如果是 quantitative，阅读 Empirical Package",
    "Step 5: 如果是 quantitative，产出量化深度分析（可信度/可迁移性/因子/回测）"
  ],
  "content": {
    "core": {
      "text_parts": {...},           # title, abstract, intro, conclusions, captions
      "figure_paths": [              # figure 图片路径，供视觉分析
        "scanned/{doc_id}/figures/fig1.png",
        "scanned/{doc_id}/figures/fig2.png"
      ]
    },
    "empirical": {...}
  }
}
```

**Subagent 输出**：

```json
{
  "doc_id": "elsevier_10.1111_jofi.70040",
  "paper_type": "quantitative",
  "basic_analysis": {
    "goals_and_contributions": "...",
    "key_methods": "...",
    "quant_value": "...",
    "further_reading": "..."
  },
  "quant_analysis": {
    "credibility_score": 72,
    "credibility_breakdown": {
      "sample_length": {"score": 20, "max": 20, "reason": "2000-2023, 23 years"},
      "out_of_sample": {"score": 15, "max": 20, "reason": "Single split at 2010"},
      "transaction_costs": {"score": 10, "max": 15, "reason": "15bps assumed"},
      "no_lookahead": {"score": 12, "max": 15, "reason": "..."},
      "data_accessible": {"score": 15, "max": 15, "reason": "..."},
      "economics_rationale": {"score": 15, "max": 15, "reason": "..."}
    },
    "transferability": {
      "universe_compat": "compatible",
      "data_frequency": "daily",
      "cost_sensitivity": "medium",
      "option_applicable": "applicable"
    },
    "factors": [
      {
        "name": "price_momentum",
        "formula": "rank(RET(t-12, t-1))",
        "description": "..."
      }
    ],
    "backtest_summary": {
      "data_period": "2000-01 to 2023-12",
      "universe": "MSCI World + EM",
      "frequency": "monthly"
    },
    "key_findings": [...],
    "methodology_risks": [...]
  },
  "quality_notes": "High-quality paper with solid theoretical grounding. Main concern: limited OOS validation."
}
```

### 4.4 P4-P5：卡片组装与索引更新

父 Agent 将 Subagent 的 JSON 渲染为标准 Markdown 卡片：

- **中文卡片 `card.md`**：完整分析（基础 + 量化深度）
- **英文卡片 `card_en.md`**：精简版（供 Factor Explorer 引用）

然后更新：
- `scan_state.json`：标记论文为 `completed`
- `scanned/index.json`：追加论文条目

---

## 5. 输出文件

### 5.1 论文卡片 `scanned/{doc_id}/card.md`

完整模板见 [卡片模板](#卡片模板)。核心结构：

```markdown
---
doc_id: ...
title: ...
title_zh: ...
authors: [...]
year: ...
source: ...
source_tier: journal | ssrn | arxiv
paper_type: quantitative | theoretical | review | empirical_non_quant | other
journal_name: ...
doi: ...
scanned_at: ...
---

## 基础分析（所有论文）
### 作者目标与贡献
### 关键方法/技术要素
### 对量化研究的实际价值
### 引申阅读线索

## 量化深度分析（仅 quantitative 论文）
### 方法论可信度评分
### 可迁移性评估
### 因子与回测
### 关键发现
### 方法论风险

## 质量总评
```

### 5.2 英文精简卡片 `scanned/{doc_id}/card_en.md`

```markdown
---
doc_id: ...
ref: "Author (Year), Journal"
---

## Summary
**Goal**: ...
**Key Contribution**: ...
**Quant Value**: ...
**Credibility**: score/tier
**Transferability**: summary
**Key Metrics**: ...
**Risks**: ...
```

### 5.3 全局索引 `scanned/index.json`

```json
{
  "last_updated": "2026-06-03T12:00:00Z",
  "total_scanned": 150,
  "by_tier": {"journal": 89, "ssrn": 42, "arxiv": 19},
  "by_type": {"quantitative": 67, "theoretical": 45, "review": 28, "other": 10},
  "papers": [
    {
      "doc_id": "elsevier_10.1111_jofi.70040",
      "title": "The Cross-Section of Momentum...",
      "authors": ["John Doe", "Jane Smith"],
      "year": 2024,
      "source": "elsevier",
      "source_tier": "journal",
      "paper_type": "quantitative",
      "credibility_score": 72,
      "credibility_tier": "green",
      "card_paths": {
        "zh": "scanned/elsevier_10.1111_jofi.70040/card.md",
        "en": "scanned/elsevier_10.1111_jofi.70040/card_en.md"
      },
      "quant_summary": {
        "best_sharpe": 1.05,
        "universe": "MSCI World + EM",
        "key_factors": ["price_momentum", "fundamental_momentum"]
      },
      "scanned_at": "2026-06-03T10:00:00Z"
    }
  ]
}
```

**排序规则**：
1. 主排序：`source_tier` 优先级（journal > ssrn > arxiv）
2. 次排序：`credibility_score` 降序
3. 第三排序：`year` 降序

### 5.4 扫描状态 `scan_state.json`

```json
{
  "last_updated": "2026-06-03T12:00:00Z",
  "total_papers": 150,
  "stats": {
    "pending": 70,
    "preprocessing": 0,
    "scanning": 3,
    "completed": 75,
    "failed": 2
  },
  "config": {
    "max_concurrent": 3,
    "priority_rules": ["source_tier", "year_desc", "added_at_desc"]
  },
  "papers": {
    "elsevier_10.1111_jofi.70040": {
      "filepath": "raw/elsevier/2026/wiley_10.1111_jofi.70040.pdf",
      "status": "completed",
      "card_path": "scanned/elsevier_10.1111_jofi.70040/card.md",
      "card_path_en": "scanned/elsevier_10.1111_jofi.70040/card_en.md",
      "paper_type": "quantitative",
      "scanned_at": "2026-06-03T10:00:00Z"
    },
    "ssrn_4801234": {
      "filepath": "raw/ssrn/ssrn_4801234.pdf",
      "status": "pending"
    },
    "arxiv_2501.12345": {
      "filepath": "raw/arxiv_qfin_tr/2501.12345.pdf",
      "status": "scanning",
      "subagent_id": "agent_20260603_001",
      "started_at": "2026-06-03T11:00:00Z"
    }
  }
}
```

**状态流转**：`pending → preprocessing → scanning → completed / failed / skipped`

---

## 6. 触发方式

| 方式 | 说明 | 阶段 |
|------|------|------|
| **手动触发** | 用户对 Agent 说「扫描论文」，可附带过滤条件 | 初期唯一方式 |
| **增量自动** | paper-downloading 完成后自动将新论文加入 queue | Phase 2 |
| **定时触发** | 每日/每周扫描增量 | Phase 2 |

**中断指令**：
- 「暂停扫描」→ 完成当前运行中的 Subagent，不再启动新任务
- 「恢复扫描」→ 从 scan_state 加载，继续处理 pending 队列
- 「跳过这篇」→ 标记当前论文为 skipped，继续下一篇

---

## 7. 与 Factor Explorer 的接口

Factor Explorer 通过以下方式消费卡片池：

1. **读取 `scanned/index.json`**：获取论文列表，按可信度筛选
2. **读取 `{doc_id}/card.md`**：获取单篇论文的完整分析
3. **读取 `{doc_id}/card_en.md`**：获取精简版用于报告引用
4. **筛选条件**：
   - `paper_type == "quantitative"` → 读取量化深度分析
   - `credibility_tier == "green"` → 优先引用
   - `source_tier == "journal"` → 高可信度

Paper Scanner 保证：
- 卡片格式稳定，不因版本更新而破坏 Factor Explorer 的读取
- `index.json` 中始终包含 `card_paths` 字段，方便定位
- `paper_type` 字段明确，Factor Explorer 可据此决定读取深度

---

## 8. Skill 目录结构

```
agent_configs/paper_manager/skills/paper-scanning/
├── SKILL.md                        # 主 skill 文档
├── references/
│   ├── card-template.md            # 卡片模板完整规范
│   ├── preprocessing-guide.md      # PDF 分片脚本使用指南
│   ├── subagent-prompt.md          # Subagent 系统提示模板
│   └── workflow-examples.md        # 典型 workflow 示例
├── scripts/
│   ├── slice_pdf.py                # PDF 智能内容分片
│   ├── build_index.py              # 从 scan_state 生成 index.json
│   └── verify_card.py              # 卡片格式校验
└── .agent_checkpoint.json          # skill 完成标记
```

### 8.1 SKILL.md 核心结构

参考 skill authoring best practices：

- **YAML Frontmatter**：name, description（触发条件）
- **Quick Start**：常见命令速查
- **Workflow**：带 checklist 的完整流程
- **References**：渐进式披露，详细内容指向 reference 文件
- **Scripts**：工具脚本说明

### 8.2 脚本层边界

| 脚本负责 | Agent 负责 |
|----------|-----------|
| PDF 结构解析与内容分片 | 论文理解与分析判断 |
| 关键词匹配（量化检测）| paper_type 最终判断 |
| 索引文件格式生成 | 卡片内容组装 |
| 卡片格式校验 | 质量总评与行动建议 |

---

## 9. 文件清单

| 路径 | 类型 | 说明 |
|------|------|------|
| `agent_configs/paper_manager/skills/paper-scanning/SKILL.md` | 新建 | Scanner skill 主文档 |
| `agent_configs/paper_manager/skills/paper-scanning/references/card-template.md` | 新建 | 卡片模板规范 |
| `agent_configs/paper_manager/skills/paper-scanning/references/preprocessing-guide.md` | 新建 | PDF 分片指南 |
| `agent_configs/paper_manager/skills/paper-scanning/references/subagent-prompt.md` | 新建 | Subagent 提示模板 |
| `agent_configs/paper_manager/skills/paper-scanning/scripts/slice_pdf.py` | 新建 | PDF 智能分片脚本 |
| `agent_configs/paper_manager/skills/paper-scanning/scripts/build_index.py` | 新建 | 索引构建脚本 |
| `agent_configs/paper_manager/skills/paper-scanning/scripts/verify_card.py` | 新建 | 卡片校验脚本 |
| `shared_workspace/papers/scanned/index.json` | 新建 | 全局索引 |
| `shared_workspace/papers/scanned/{doc_id}/` | 新建目录 | 论文卡片存储 |
| `shared_workspace/papers/scan_state.json` | 新建 | 扫描状态 |

---

*设计日期：2026-06-03*
*配套设计：[Factor Explorer Agent 设计规格](2026-05-28-factor-explorer-design.md)*
*状态：已审查*
