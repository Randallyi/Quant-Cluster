# Quant Cluster Skill Standardization + validate.py Design

**Date:** 2026-05-17  
**Scope:** P0 upgrades inspired by Anthropic financial-services repository  
**Status:** Approved

---

## Goal

将 Anthropic financial-services 仓库的 P0 可借鉴设计整合到 quant-cluster：

1. **Skill 标准化格式**：为每个 Agent 的 `SOUL.md` 增加 YAML frontmatter + 结构化章节 + 检查清单
2. **validate.py 统一验证**：开发时手动运行 + git pre-commit hook 自动检查

---

## Design Decisions

### 1. Migration Strategy: Progressive (渐进式)

- **保留所有现有 SOUL.md 内容**，不改变其作为 Agent system prompt 的核心作用
- **增加 YAML frontmatter**（`---` 包裹的 metadata 块），Orchestrator 读取时自动忽略 frontmatter
- **正文结构化为固定章节**，便于人类阅读和后续自动化解析
- **不拆分 skill 目录**，保持 "一个 Agent = 一个 SOUL.md" 的现有架构

### 2. Standardized SOUL.md Format

每个 SOUL.md 开头增加：

```yaml
---
name: hypothesis
description: |
  文献调研 + 可检验假设生成。接收研究主题，输出假设报告（中英双语）、
  数据需求清单、引用文献索引。
triggers:
  - 研究主题输入（自然语言描述）
  - "研究一下 XXX"
skills:
  - literature-review
  - data-requirements
  - reference-validation
input_spec:
  - 来源: orchestrator prompt
    格式: 自然语言研究主题
output_spec:
  - hypothesis_{topic_slug}.md          # 中文假设报告
  - hypothesis_{topic_slug}_en.md       # 英文假设报告
  - data_requirements.json              # 数据需求清单
  - references.json                     # 引用文献索引
  - .agent_checkpoint.json              # 完成标记
dependencies:
  - tools/webbridge_client.py
  - Tavily API (web_search)
---
```

正文固定章节（保留现有内容，重新组织）：

```markdown
# 🎯 [Agent Name]

## 角色定义
（现有内容）

## 触发条件
- 何时激活此 Agent
- 输入期望

## 核心能力
（工具配额、可用技能）

## 工作流（Phase 1-N）
（分阶段描述，参考 Anthropic 的 Phase 格式）

## 产出规范
- 文件名模式
- 内容要求
- 格式要求

## 验证检查清单
- [ ] 产出 A 已生成
- [ ] 产出 B 已生成
- [ ] 数据完整性检查通过

## 禁止事项
- ❌ ...

## 依赖
- 文件/工具/API
```

### 3. validate.py 验证脚本

检查项：

| # | 检查项 | 说明 |
|---|--------|------|
| 1 | Frontmatter 完整性 | 每个 SOUL.md 必须有 `name`, `description`, `output_spec` |
| 2 | YAML 语法有效性 | frontmatter 必须是合法 YAML |
| 3 | DAG 一致性 | `dag.py` 中声明的 workspace 路径必须在文件系统存在 |
| 4 | Output spec 一致性 | DAG 中的 `output_files` 模式必须和 SOUL.md frontmatter 中的 `output_spec` 一致 |
| 5 | 双语成对检查 | 每个中文 `.md` 产出声明必须有对应的 `_en.md` |
| 6 | Config 有效性 | `config.yaml` 必须是合法 YAML |
| 7 | 交叉引用检查 | SOUL.md 中引用的 `/workspace/XX_xxx/` 路径是否存在于 DAG |
| 8 | Required files | 每个 agent 目录必须有 `SOUL.md` 和 `config.yaml` |

脚本设计：
- `scripts/validate.py` — 主脚本，exit 0 表示通过，exit 1 表示失败
- 支持 `python scripts/validate.py --fix` 自动修复简单问题（如添加缺失的 frontmatter）
- 输出格式：清晰的错误列表，每条带文件路径和具体原因
- 内置 `ensure_hooks_installed()` 自动配置 git hooks

### 4. Git Pre-commit Hook

- `.githooks/pre-commit` — 在 commit 前自动运行 `scripts/validate.py`
- `scripts/validate.py` 内置 `ensure_hooks_installed()` 函数，首次运行时自动配置 `core.hooksPath`
- 如果验证失败，commit 被阻止，打印错误列表

### 5. Backward Compatibility

- Orchestrator 读取 SOUL.md 时，现有的 prompt 传递逻辑**完全不变**
- Hermes Agent 读取 SOUL.md 作为 system prompt 时，frontmatter 被当作 markdown 的一部分，不影响行为
- 未来如需让 Orchestrator 解析 frontmatter，可在 `orchestrator/core/dag.py` 中增加 `AgentConfig` 类，渐进式引入

---

## Files to Modify / Create

### 修改现有文件
- `agent_configs/hypothesis/SOUL.md`
- `agent_configs/data_engineer/SOUL.md`
- `agent_configs/quant_analyst/SOUL.md`
- `agent_configs/risk_auditor/SOUL.md`
- `agent_configs/strategy_writer/SOUL.md`

### 新增文件
- `scripts/validate.py` — 验证脚本
- `.githooks/pre-commit` — git pre-commit hook
- `docs/superpowers/specs/2026-05-17-skill-standardization-design.md` — 本设计文档

---

## Implementation Steps

1. **Step 1**: 创建 `scripts/validate.py` 框架
2. **Step 2**: 改造 `hypothesis/SOUL.md` 作为试点
3. **Step 3**: 运行 validate.py 验证试点，调整格式
4. **Step 4**: 批量改造其余 4 个 Agent 的 SOUL.md
5. **Step 5**: 完善 validate.py（增加检查项 4-8）
6. **Step 6**: 配置 git pre-commit hook
7. **Step 7**: 全量验证，确保通过
8. **Step 8**: 更新 SKILL.md 文档

---

## Success Criteria

- [ ] `python scripts/validate.py` 运行后 exit 0，0 issues
- [ ] 每个 Agent 的 SOUL.md 都有完整的 YAML frontmatter
- [ ] git commit 时自动触发验证，配置错误被阻止
- [ ] 现有 pipeline（`orchestrator.cli run`）不受影响，dry-run 通过

---

## Risk & Mitigation

| 风险 | 缓解措施 |
|------|---------|
| Frontmatter 被 Hermes 当作 prompt 的一部分，影响行为 | Frontmatter 是纯 metadata，不会生成有害内容；且现有内容完全保留 |
| validate.py 引入新的 Python 依赖 | 仅使用标准库（`yaml` 可选，失败时优雅降级） |
| 批量修改 5 个 SOUL.md 引入不一致 | 先试点 1 个，验证通过后再批量复制模板 |
