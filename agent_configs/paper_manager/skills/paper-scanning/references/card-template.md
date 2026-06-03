# Card Templates

This document defines the exact frontmatter and section structure for bilingual paper cards.

---

## Chinese Card (`card.md`)

```markdown
---
doc_id: arxiv_2401_12345
title: "论文标题"
authors:
  - "作者 A"
  - "作者 B"
year: 2024
source: "arXiv q-fin.TR"
source_tier: arxiv
paper_type: quantitative
credibility_score: 78
credibility_tier: B
quant_summary:
  factors:
    - "动量因子 (Momentum)"
    - "价值因子 (HML)"
  backtest_period: "2000-01 至 2023-12"
  sharpe_reported: 1.42
  data_frequency: "日度"
  asset_class: "美股大盘股"
---

# 论文标题

## 元数据

- **来源**: arXiv q-fin.TR
- **年份**: 2024
- **作者**: 作者 A, 作者 B
- **文档 ID**: arxiv_2401_12345
- **可信度等级**: B (78/100)

## 摘要

（中文摘要，约 150-300 字）

## 核心贡献

1. 贡献一
2. 贡献二
3. 贡献三

## 方法论概述

（研究方法、数据来源、模型框架的概述）

## 量化深度分析

（仅当 `paper_type == "quantitative"` 时必填）

- **因子定义**: 因子如何构建、清洗、中性化
- **回测设置**: 交易成本假设、再平衡频率、样本内外划分
- **统计方法**: 回归模型、检验方法、显著性水平
- **数据描述**: 数据源、时间跨度、频率、覆盖范围

## 方法论可信度评分

（仅当 `paper_type == "quantitative"` 时必填）

| 维度 | 得分 | 说明 |
|------|------|------|
| 数据质量 | 14/20 | 说明 |
| 方法严谨性 | 16/20 | 说明 |
| 结果可复制性 | 12/20 | 说明 |
| 经济学意义 | 15/20 | 说明 |
| 统计显著性 | 13/20 | 说明 |
| 论文来源/引用 | 8/20 | 说明 |
| **总分** | **78/100** | |

## 可迁移性评估

（仅当 `paper_type == "quantitative"` 时必填）

- **市场可迁移性**: 是否适用于 A 股、港股、期货等其他市场
- **频率可迁移性**: 方法是否可应用于分钟级、周度等不同频率
- **资产类别可迁移性**: 是否可扩展至债券、商品、加密资产等
- **实施难度**: 高 / 中 / 低

## 因子与回测

（仅当 `paper_type == "quantitative"` 时必填）

- **核心因子**: 列表及定义
- **回测表现**: 报告的收益、风险指标、最大回撤
- **交易成本敏感性**: 是否测试了不同成本假设下的稳健性
- **过拟合风险**: 参数数量 vs 样本量、是否使用交叉验证

## 关键发现

（仅当 `paper_type == "quantitative"` 时必填）

- 发现一（附显著性水平或效应量）
- 发现二
- 发现三

## 方法论风险

（仅当 `paper_type == "quantitative"` 时必填）

- **幸存者偏差**: 是否处理
- **前瞻偏差 (Look-ahead bias)**: 是否处理
- **数据窥探 (Data snooping)**: 是否处理
- **交易成本遗漏**: 是否考虑滑点、市场冲击
- **其他弱点**: 子样本不稳定、流动性假设不现实等

## 结论

（论文总体评价，是否值得纳入因子库或策略研究）
```

---

## English Card (`card_en.md`)

```markdown
---
doc_id: arxiv_2401_12345
title: "Paper Title"
authors:
  - "Author A"
  - "Author B"
year: 2024
source: "arXiv q-fin.TR"
source_tier: arxiv
paper_type: quantitative
credibility_score: 78
credibility_tier: B
quant_summary:
  factors:
    - "Momentum"
    - "Value (HML)"
  backtest_period: "2000-01 to 2023-12"
  sharpe_reported: 1.42
  data_frequency: "Daily"
  asset_class: "US Large-Cap Equities"
---

# Paper Title

## Metadata

- **Source**: arXiv q-fin.TR
- **Year**: 2024
- **Authors**: Author A, Author B
- **Doc ID**: arxiv_2401_12345
- **Credibility Tier**: B (78/100)

## Abstract

(English abstract, 150-300 words)

## Core Contributions

1. Contribution one
2. Contribution two
3. Contribution three

## Methodology Overview

(Summary of research methods, data sources, and model framework)

## Quantitative Deep Dive

(Required when `paper_type == "quantitative"`)

- **Factor Definition**: How factors are constructed, cleaned, and neutralized
- **Backtest Setup**: Transaction cost assumptions, rebalancing frequency, in/out-of-sample split
- **Statistical Methods**: Regression models, test methods, significance levels
- **Data Description**: Data sources, time span, frequency, coverage

## Methodology Credibility Score

(Required when `paper_type == "quantitative"`)

| Dimension | Score | Notes |
|-----------|-------|-------|
| Data Quality | 14/20 | Notes |
| Methodological Rigor | 16/20 | Notes |
| Reproducibility | 12/20 | Notes |
| Economic Significance | 15/20 | Notes |
| Statistical Significance | 13/20 | Notes |
| Source / Citations | 8/20 | Notes |
| **Total** | **78/100** | |

## Transferability Assessment

(Required when `paper_type == "quantitative"`)

- **Market Transferability**: Applicable to A-shares, HK equities, futures, etc.
- **Frequency Transferability**: Applicable to minute-level, weekly, etc.
- **Asset Class Transferability**: Extensible to bonds, commodities, crypto, etc.
- **Implementation Difficulty**: High / Medium / Low

## Factors & Backtest

(Required when `paper_type == "quantitative"`)

- **Core Factors**: List and definitions
- **Backtest Performance**: Reported returns, risk metrics, max drawdown
- **Transaction Cost Sensitivity**: Robustness under different cost assumptions
- **Overfitting Risk**: Number of parameters vs sample size, cross-validation usage

## Key Findings

(Required when `paper_type == "quantitative"`)

- Finding one (with significance level or effect size)
- Finding two
- Finding three

## Methodological Risks

(Required when `paper_type == "quantitative"`)

- **Survivorship Bias**: Addressed or not
- **Look-ahead Bias**: Addressed or not
- **Data Snooping**: Addressed or not
- **Transaction Cost Omission**: Slippage and market impact considered or not
- **Other Weaknesses**: Subsample instability, unrealistic liquidity assumptions, etc.

## Conclusion

(Overall evaluation — whether the paper is worth adding to the factor zoo or strategy research pipeline)
```

---

## Field Explanations

| Field | Type | Description |
|-------|------|-------------|
| `doc_id` | string | Unique identifier, usually the PDF filename stem. |
| `title` | string | Full paper title. |
| `authors` | list[string] | Author names in order of appearance. |
| `year` | integer | Publication year. |
| `source` | string | Human-readable source name (e.g., "arXiv q-fin.TR", "Journal of Finance"). |
| `source_tier` | enum | One of `journal`, `ssrn`, `arxiv`. Used for sorting priority. |
| `paper_type` | enum | One of `quantitative`, `theoretical`, `review`, `empirical_non_quant`, `other`. |
| `credibility_score` | integer | 0-100, computed by Subagent across 6 dimensions. |
| `credibility_tier` | string | A/B/C/D/F mapped from score ranges (e.g., 90-100=A, 80-89=B). |
| `quant_summary` | object | **Optional.** Condensed quantitative metadata for index generation. Contains `factors`, `backtest_period`, `sharpe_reported`, `data_frequency`, `asset_class`. |

## Validation Rules

`verify_card.py` enforces the following:

1. **Frontmatter** must contain all 7 required fields.
2. `source_tier` must be one of `journal`, `ssrn`, `arxiv`.
3. `paper_type` must be one of `quantitative`, `theoretical`, `review`, `empirical_non_quant`, `other`.
4. If `paper_type == "quantitative"`, the body must contain **all** of these section headers exactly:
   - `## 量化深度分析`
   - `## 方法论可信度评分`
   - `## 可迁移性评估`
   - `## 因子与回测`
   - `## 关键发现`
   - `## 方法论风险`
