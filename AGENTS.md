# Quant Cluster Agent Configuration Specification

> 本文件定义 Quant Cluster 中 Agent 配置的标准格式和验证规则。
>  inspired by [Anthropic financial-services](https://github.com/anthropics/financial-services).

---

## 目录结构

```
agent_configs/
├── hypothesis/
│   ├── SOUL.md        ← Agent 系统提示 + 技能定义（标准化格式）
│   └── config.yaml    ← Hermes 运行时配置
├── data_engineer/
│   ├── SOUL.md
│   └── config.yaml
├── quant_analyst/
│   ├── SOUL.md
│   └── config.yaml
├── risk_auditor/
│   ├── SOUL.md
│   └── config.yaml
└── strategy_writer/
    ├── SOUL.md
    └── config.yaml
```

---

## SOUL.md 标准格式

每个 `SOUL.md` 必须包含 YAML frontmatter + 结构化正文。

### YAML Frontmatter（必须）

```yaml
---
name: hypothesis                              # Agent 标识名
description: |                                # 一句话描述职责
  文献调研 + 可检验假设生成。
triggers:                                     # 触发条件列表
  - 研究主题输入（自然语言描述）
  - "研究一下 XXX"
skills:                                       # 技能列表
  - literature-review
  - reference-validation
input_spec:                                   # 输入规范
  - 来源: orchestrator prompt
    格式: 自然语言研究主题
output_spec:                                  # 输出文件列表（必须）
  - hypothesis_{topic_slug}.md                # 中文产出
  - hypothesis_{topic_slug}_en.md             # 英文产出
  - data_requirements.json
  - .agent_checkpoint.json                    # 完成标记
dependencies:                                 # 依赖项
  - tools/webbridge_client.py
  - Tavily API (web_search)
---
```

**必填字段**：`name`, `description`, `output_spec`

**输出文件命名约定**：
- 中文报告：`{name}_{identifier}.md`
- 英文报告：`{name}_{identifier}_en.md`
- 完成标记：`.agent_checkpoint.json`（每个 Agent 必须有）

### 正文章节（推荐顺序）

```markdown
# 🎯 [Agent Name]

## 角色定义
## 触发条件
## 核心能力
## 工作流（Phase 1-N）
## 产出规范
## 验证检查清单
## [其他专题章节]
## 禁止事项
```

### 验证检查清单格式

使用 GitHub-flavored Markdown 任务列表：

```markdown
## 验证检查清单

产出前逐条核对：

- [ ] **数据完整性**：所有必需数据已获取
- [ ] **双语完整性**：中文报告 + 英文报告均已生成
- [ ] **checkpoint 写入**：`.agent_checkpoint.json` 已生成
```

---

## config.yaml 规范

- 必须是合法 YAML
- 包含 `model`, `api_server`, `tools` 等 Hermes 配置
- 每个 Agent 的 `api_server.port` 必须与 `orchestrator/core/dag.py` 中的 `AGENTS` 定义一致

---

## 验证脚本

### 运行验证

```bash
# 验证所有 Agent 配置
python3 scripts/validate.py

# 自动修复简单问题
python3 scripts/validate.py --fix

# 详细输出
python3 scripts/validate.py --verbose

# 安装 git hooks
python3 scripts/validate.py --install-hooks
```

### 验证检查项

| # | 检查项 |
|---|--------|
| 1 | Frontmatter 完整性（`name`, `description`, `output_spec`） |
| 2 | YAML 语法有效性 |
| 3 | DAG 一致性（workspace 路径、执行顺序） |
| 4 | Output spec 一致性（SOUL.md vs DAG） |
| 5 | 双语成对检查（中文 `.md` ↔ `_en.md`） |
| 6 | Config 有效性（合法 YAML） |
| 7 | 交叉引用检查（workspace 路径存在性） |
| 8 | 必需文件检查（`SOUL.md` + `config.yaml`） |

### Git Pre-commit Hook

首次运行 `scripts/validate.py` 时自动安装 `.githooks/pre-commit`。此后每次 `git commit` 会自动运行验证，失败时阻止提交。

如需手动安装：
```bash
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit
```

---

## 向后兼容性说明

- **Orchestrator**：读取 `SOUL.md` 作为 prompt 时，frontmatter 被当作普通 markdown 文本，不影响行为
- **Hermes Agent**：`SOUL.md` 作为 system prompt 传递时，frontmatter 无害，现有内容完全保留
- 未来如需让 Orchestrator 解析 frontmatter，可在 `orchestrator/core/dag.py` 中渐进式引入 `AgentConfig` 类

---

## 修改 Agent 配置的工作流

1. 编辑 `agent_configs/{agent}/SOUL.md`
2. 运行 `python3 scripts/validate.py` 检查
3. 修复错误（可用 `--fix` 自动修复简单问题）
4. `git add` + `git commit`（pre-commit hook 会自动验证）
