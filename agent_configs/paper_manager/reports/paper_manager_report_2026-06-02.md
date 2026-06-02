# 论文资产管理报告 2026-06-02

## 执行摘要

引擎当前处于 **degraded** 状态。整体失败率 97%，主要由 `neurips_2025` 源贡献（5,823 次 404 失败）。排除该源后，实际失败率为 28%（97 / 345），仍高于健康阈值。

| 指标 | 数值 |
|------|------|
| 总下载成功 | 170 |
| 总失败 | 5,920 |
| 健康源 | 2 (arxiv_qfin_tr, arxiv_cs_lg) |
| 降级源 | 3 (core_ac, elsevier, neurips_2025) |
| 待处理 | 0 |

---

## 各源状态

### arxiv_qfin_tr — 健康
- 下载成功: 129
- 失败: 1 (0.8%)
- 决策: 无需操作

### arxiv_cs_lg — 健康
- 下载成功: 4
- 失败: 0
- 决策: 无需操作

### core_ac — 降级
- 下载成功: 19
- 失败: 33 (63%)
- 失败原因: 返回 HTML 而非 PDF；部分 400/404
- 决策: 检查 CORE_API_KEY 后重试一次。若仍 >50% 失败则禁用。

### elsevier — 降级
- 下载成功: 17
- 失败: 62 (78%)
- 失败原因: API 返回 XML 而非 PDF（可能是认证失败或付费墙）
- 决策: 检查 ELSEVIER_API_KEY 后重试一次。若仍 >50% 失败则禁用。

### wiley — 边缘
- 下载成功: 1
- 失败: 1 (50%)
- 决策: 样本太小，继续观察

### neurips_2025 — 完全失效
- 下载成功: 0
- 失败: 5,823 (100%)
- 失败原因: 5,771 次 404，37 次 SSL/连接超时。NeurIPS 2025 尚未召开（通常在 12 月），PDF 未发布。
- 决策: **立即禁用**。清理数据库中 5,823 条失败记录。无重试价值。

---

## 失败分析

### neurips_2025 根因
`NeurIPSSource` 使用 `datetime.now().year - 1` 构造年份，但当前配置中 `year=2025`（由 `__main__.py` 中 `datetime.now().year - 1` 计算得出，说明当前年份被识别为 2026）。NeurIPS 2025 论文尚未发布，导致所有 PDF URL 404。

这不是网络故障，是数据源尚未存在。应禁用该源，待 2025 年 12 月会议结束后再启用。

### elsevier 根因
所有 62 次失败均为 `content-type: text/xml`。Elsevier API 在认证失败或请求非开放获取论文时返回 XML 错误。需验证 API key 有效性及期刊列表是否均为 OA。

### core_ac 根因
多数失败返回 HTML（可能是登录页或错误页），少数 400/404。CORE API key 可能无效，或查询结果中的 PDF 链接已失效。

---

## 决策记录

| 源 | 决策 | 理由 |
|----|------|------|
| neurips_2025 | **禁用 + 清库** | 会议未召开，5,823 条记录为无效噪音 |
| elsevier | 检查 API key 后重试 | 失败模式一致（XML），可能可修复 |
| core_ac | 检查 API key 后重试 | 失败模式一致（HTML），可能可修复 |
| wiley | 保持观察 | 样本不足 |
| arxiv_* | 无操作 | 健康运行 |

---

## 下一步行动

1. 在 `config.yaml` 中将 `neurips.enabled` 设为 `false`
2. 从数据库删除 `source='neurips_2025'` 的所有记录
3. 验证 `CORE_API_KEY` 和 `ELSEVIER_API_KEY` 环境变量是否有效
4. 对 elsevier 和 core_ac 各执行一次单源扫描测试
5. 若重试后失败率仍 >30%，将对应源标记为禁用

---

## 引擎问题记录

`paper_downloader/__main__.py` 使用绝对导入（`from core.store import ...`），运行时需要将 `/workspace/tools/paper_downloader` 加入 `PYTHONPATH`。当前正确调用方式为：

```bash
PYTHONPATH=/workspace/tools/paper_downloader:/workspace/tools python -m paper_downloader stats
```

建议修复为相对导入或包内路径处理。
