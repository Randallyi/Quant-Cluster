# Quant Cluster Pipeline 可靠性修复 — 设计文档

> **日期**: 2026-05-17
> **主题**: 修复 Hypothesis Agent 错误循环、WebBridge 调用 bug、SSE 断连问题，使全 Pipeline 可稳定跑通
> **测试主题**: "动量与反转的边界条件"

---

## 1. 执行摘要

### 当前状态

Pipeline 在 **Hypothesis Agent 阶段卡住**，无法走到后续步骤。通过对 `agent_configs/hypothesis/sessions/` 中两个完整 session（共 22 分钟运行日志）的逐条分析，发现 Agent **有能力完成工作**（成功执行了 50+ 次 web_search 和 WebBridge 调用），但被三个工程问题阻止：

1. **`webbridge_client.py fetch` 命令存在 bug** — 误报 navigate 失败，迫使 Agent 使用额外的 `snapshot` 调用
2. **Agent 在 DOM selector 不匹配时陷入重复重试循环** — 对同一 selector 连续执行 7 次，不根据错误反馈调整策略
3. **SSE 流式传输不稳定导致 session 被强制中断** — 第一个 session 在 7 分钟后被 `SSE client disconnected` 中断

### 修复策略（非降级）

| 优先级 | 修复项 | 说明 |
|--------|--------|------|
| P0 | 修复 `webbridge_client.py` 的 `fetch` bug | 核心基础设施修复 |
| P0 | 重写 Hypothesis SOUL.md | 消除矛盾指令，增加 DOM 错误恢复策略，明确 Tavily 使用边界 |
| P0 | 调整 Hermes Config（5 个 Agent） | 移除 `browser` 工具，增加 terminal timeout |
| P1 | 调整 Orchestrator | 非 stream 默认，增加 hypothesis 超时 |
| P1 | PDF 获取策略 | 通过 WebBridge `evaluate` + `fetch` API 在宿主机 Chrome 上下载 |
| P2 | 逐个 Agent 测试并整理 Skill | 从 hypothesis 开始，用"动量与反转的边界条件"验证 |

---

## 2. 详细问题分析

### 2.1 问题 1：`webbridge_client.py fetch` 命令 Bug

**代码位置**: `tools/webbridge_client.py` 第 67-72 行

**问题代码**:
```python
def cmd_fetch(args):
    r1 = api_request("navigate", {"url": args.url, "newTab": True}, args.session)
    if not r1.get("success"):  # ← BUG: WebBridge API 返回格式是 {"ok": true, "data": {"success": true}}
        print(json.dumps({"navigate_error": r1}, indent=2))
        return
    r2 = api_request("snapshot", {}, args.session)
    print(json.dumps(r2, indent=2))
```

**WebBridge API 响应格式**:
```json
{"ok": true, "data": {"success": true, "url": "...", "tabId": 123}}
```

`r1.get("success")` 永远返回 `None`/`False`，因为 `success` 在 `data` 内部，不在顶层。

**影响**:
- `fetch` 命令总是返回 `{"navigate_error": {...}}`，即使 navigate 成功
- Agent 被迫使用 `navigate` + `snapshot` 两步调用，增加 API 调用次数和失败面
- 部分 Agent 在收到 "navigate_error" 后困惑，浪费时间

**修复**:
```python
def cmd_fetch(args):
    r1 = api_request("navigate", {"url": args.url, "newTab": True}, args.session)
    if not (r1.get("ok") and r1.get("data", {}).get("success")):
        print(json.dumps({"navigate_error": r1}, indent=2))
        return
    r2 = api_request("snapshot", {}, args.session)
    print(json.dumps(r2, indent=2))
```

### 2.2 问题 2：Agent DOM Selector 循环

**Session 证据** (`api-96df9854a4436652`):
```
Tool: evaluate
  code: document.querySelector('div.abstract').innerText
  → TypeError: Cannot read properties of null (reading 'innerText')

（重复 7 次同样的调用，Agent 不调整 selector）
```

**根因**: SOUL.md 中没有给 Agent 提供 DOM 元素不存在时的恢复策略。Agent "固执"地重复同一操作，不根据错误反馈学习。

**修复方向**（在 SOUL.md 中增加）:
- 当 `evaluate` 连续 2 次返回 `null` / `TypeError` 时，改用兜底策略：
  ```javascript
  Array.from(document.querySelectorAll('p')).map(p => p.innerText).join('\n---\n').slice(0, 5000)
  ```
- 如果兜底策略也失败，记录该页面"结构不可解析"，继续下一个信息源
- **禁止对同一 selector 重复执行超过 3 次**

### 2.3 问题 3：SSE 断连

**Session 证据** (`api-d09e0ca78d024b2f`):
```
SSE client disconnected; interrupted agent task chatcmpl-342ff2fe1ff64d528acdb16f11940
Streaming failed before delivery: [Errno 9] Bad file descriptor
```

**根因**: Orchestrator 使用 `stream=True` 模式调用 Agent，SSE 连接在长时间运行（>7 分钟）时不稳定。

**修复**: Orchestrator 默认使用 `stream=False`，hypothesis 的超时从 1800s 增加到 3600s。

### 2.4 问题 4：SOUL.md 内部矛盾

| 矛盾点 | 说明 |
|--------|------|
| 禁止 `browser` 但 config 启用了它 | SOUL.md 说"禁止使用 browser 工具"，但 `config.yaml` 的 `tools.enabled` 包含 `browser`，且 Hermes 将 browser 函数注册到了 function calling schema 中 |
| Tavily 使用边界模糊 | SOUL.md 说 Tavily 是"首选搜索工具"，但用户要求 Tavily 仅限"解释不熟悉的金融/计量经济学专业概念" |
| web_extract 策略矛盾 | 先说"严禁使用 web_extract"，后说"web_extract 失败后最多重试 1 次" |

---

## 3. 修复方案

### 3.1 修复 `webbridge_client.py`

**文件**: `tools/webbridge_client.py`

**修改 1：修复 `fetch` 命令的 bug**:
```python
def cmd_fetch(args):
    r1 = api_request("navigate", {"url": args.url, "newTab": True}, args.session)
    if not (r1.get("ok") and r1.get("data", {}).get("success")):
        print(json.dumps({"navigate_error": r1}, indent=2))
        return
    r2 = api_request("snapshot", {}, args.session)
    print(json.dumps(r2, indent=2))
```

**修改 2：增加 `download` 命令（用于 PDF 获取）**:
```python
def cmd_download(args):
    """Download a file via WebBridge (uses host Chrome's session/cookies).
    
    Returns base64-encoded content that the agent can decode and save.
    """
    # First navigate to establish session context
    r1 = api_request("navigate", {"url": args.url, "newTab": True}, args.session)
    if not (r1.get("ok") and r1.get("data", {}).get("success")):
        print(json.dumps({"navigate_error": r1}, indent=2))
        return
    
    # Use evaluate to fetch the file via browser's fetch API
    fetch_code = f'''
        fetch("{args.url}")
            .then(r => r.ok ? r.arrayBuffer() : Promise.reject(r.statusText))
            .then(buf => {{
                const bytes = new Uint8Array(buf);
                const base64 = btoa(Array.from(bytes, b => String.fromCharCode(b)).join(''));
                return {{success: true, base64: base64, size: bytes.length}};
            }})
            .catch(e => ({{success: false, error: e.toString()}}));
    '''
    r2 = api_request("evaluate", {"code": fetch_code}, args.session)
    print(json.dumps(r2, indent=2))
```

**修改 3：增加 `--version` 或版本号** — 方便 Agent 确认脚本版本。

### 3.2 重写 Hypothesis Agent SOUL.md

**文件**: `agent_configs/hypothesis/SOUL.md`

**重写原则**:
- **保留 Phase 1-3 框架**：多源检索 → 交叉比对 → 深度推理
- **保留 WebBridge 作为最高优先级**信息获取手段
- **保留 `auto_learn` / `skill_manage`**：允许 Agent 在工作中自我改进
- **明确 Tavily 的受限使用场景**：仅限"解释不熟悉的金融/计量经济学专业概念"，禁止用于文献检索
- **移除 `browser` 工具的引用**：不再提及 browser，因为 config 中将禁用
- **增加 DOM 错误恢复策略**
- **增加 PDF 处理策略**
- **增加 Session 管理铁律**

**关键新增/修改内容**:

#### Tavily 使用边界（明确限制）

```markdown
## Tavily 搜索使用边界

**web_search（Tavily）的使用严格限制于以下场景**：

| 允许场景 | 示例 |
|---------|------|
| 解释不熟悉的金融/计量经济学专业概念 | "什么是 PBO (Probability of Backtest Overfitting)？" |
| 查找某个学术术语的定义 | "什么是 regime-switching model？" |
| 快速确认某个事实性信息 | "Fama-French 三因子模型是哪一年提出的？" |

**禁止场景**：
- ❌ 用 Tavily 搜索学术论文（学术网站返回空内容，100% 浪费时间）
- ❌ 用 Tavily 获取网页全文（使用 WebBridge 替代）
- ❌ 用 Tavily 作为文献调研的主要工具
```

#### WebBridge DOM 错误恢复策略

```markdown
## WebBridge 错误恢复策略

当使用 `evaluate` 提取页面元素时：

1. **首次尝试**：使用最精确的 selector（如 `document.querySelector('div.abstract').innerText`）
2. **如果返回 `null` 或 `TypeError`**：
   - 第二次尝试：扩大 selector 范围（如 `document.querySelectorAll('p')`）
   - 第三次尝试：使用兜底提取策略：
     ```javascript
     Array.from(document.querySelectorAll('p')).map(p => p.innerText).join('\n---\n').slice(0, 5000)
     ```
3. **如果 3 次都失败**：记录该页面为"结构不可解析"，关闭 session，继续下一个信息源
4. **绝对禁止**：对同一 selector 重复执行超过 3 次
```

#### PDF 处理策略

```markdown
## PDF 处理策略

对于 PDF 格式的学术文献：

1. **识别 PDF 链接**：URL 以 `.pdf` 结尾或包含 `Delivery.cfm`（SSRN）
2. **下载方式**：使用 WebBridge 的 `evaluate` 执行浏览器 `fetch` API 获取 base64 内容
3. **解码保存**：在容器内解码 base64 并保存为 `.pdf` 文件
4. **文本提取**：使用 `pdfplumber` 读取（先安装：`uv pip install --python /opt/hermes/.venv/bin/python pdfplumber`）
5. **扫描版 PDF**：如果提取为空或乱码，记录 "scan-only" 并继续
```

#### Session 管理铁律

```markdown
## Session 管理铁律

1. 每个信息源使用独立的 session 名称（如 `hypothesis-ssrn`、`hypothesis-arxiv`）
2. **每个 session 用完后必须调用 `close`**
3. 如果一个 session 超过 10 分钟未活动，主动 `close` 后重新 `fetch`
4. 同时打开的 session 不超过 3 个
```

### 3.3 调整 Hermes Config（5 个 Agent）

**文件**: `agent_configs/{hypothesis,data_engineer,quant_analyst,risk_auditor,strategy_writer}/config.yaml`

**修改**:

```yaml
tools:
  enabled:
    - web_search        # Tavily：仅限专业概念解释
    # - browser         # ← 移除：容器内无浏览器引擎，且与 WebBridge 冲突
    - terminal          # 用于调用 WebBridge 客户端、执行 Python 脚本
    - file              # 文件读写
    - memory            # memory_space_edits
    - vision            # 图像分析
    - skill_manage      # 保留：允许 Agent 自我改进

terminal:
  backend: local
  timeout: 1800        # ← 从 600 增加到 1800（文献调研需要更长时间）
  allowed_commands:
    - python3
    - uv                # ← 新增：用于安装 Python 包
    - pip
    - ls
    - cat
    - mkdir
    - curl

skills:
  auto_learn: true     # ← 保留：这是使用 Hermes 的核心原因
  hub:
    enabled: false
```

**说明**:
- `browser` 工具从 `tools.enabled` 中移除。这将阻止 Hermes 在 function calling schema 中注册 browser_navigate/browser_click 等函数，从根本上消除 Agent 被诱惑使用 browser 的可能性。
- `timeout` 增加到 1800s（30 分钟），给 Agent 足够的时间完成文献调研。
- `uv` 加入 `allowed_commands`，允许 Agent 安装 `pdfplumber` 等工具。

### 3.4 调整 Orchestrator

**文件**: `orchestrator/core/orchestrator.py`, `orchestrator/clients/hermes.py`

**修改 1：默认非 stream 模式**:
```python
# orchestrator/core/orchestrator.py
# 修改 _execute_agent 中的默认行为
if stream:
    result_text = await self._call_agent_stream(agent_name, system_prompt, user_prompt)
else:
    # 默认非 stream，更稳定
    result_text = await self.clients[agent_name].chat(system_prompt, user_prompt, timeout=3600)
```

**修改 2：增加 hypothesis 超时**:
```python
# orchestrator/clients/hermes.py
# hypothesis agent 使用更长的超时
TIMEOUTS = {
    "hypothesis": 3600,      # 1 小时：文献调研需要较长时间
    "data_engineer": 1800,   # 30 分钟
    "quant_analyst": 1800,   # 30 分钟
    "risk_auditor": 1800,    # 30 分钟
    "strategy_writer": 1800, # 30 分钟
}
```

**修改 3：增加空结果重试逻辑**:
```python
# 如果 Agent 返回空结果（可能因 SSE 断连），自动重试一次
if not result_text or result_text.strip() == "":
    console.log(f"[yellow]{agent_name} returned empty — retrying once[/yellow]")
    resume_prompt = f"{user_prompt}\n\n[SYSTEM_NOTICE] 上次响应似乎被中断了。请从上次中断的地方继续，不要重复已完成的工作。"
    result_text = await self.clients[agent_name].chat(system_prompt, resume_prompt, timeout=TIMEOUTS.get(agent_name, 1800))
```

### 3.5 PDF 获取 — 方案 A（evaluate + fetch API）

在 SOUL.md 中提供以下完整代码模板供 Agent 复制使用：

```python
import subprocess, json, base64, os

# Step 1: 安装 pdfplumber（只需执行一次）
subprocess.run([
    "uv", "pip", "install",
    "--python", "/opt/hermes/.venv/bin/python",
    "pdfplumber"
], check=True)

# Step 2: 通过 WebBridge 获取 PDF（利用宿主机 Chrome 的 session）
pdf_url = "https://papers.ssrn.com/sol3/Delivery.cfm/..."
session = "hypothesis-pdf"

fetch_code = f'''
fetch("{pdf_url}")
    .then(r => r.ok ? r.arrayBuffer() : Promise.reject(r.statusText))
    .then(buf => {{
        const bytes = new Uint8Array(buf);
        const base64 = btoa(Array.from(bytes, b => String.fromCharCode(b)).join(''));
        return {{success: true, base64: base64, size: bytes.length}};
    }})
    .catch(e => ({{success: false, error: e.toString()}}));
'''

result = subprocess.run([
    "python3", "/workspace/tools/webbridge_client.py", "evaluate",
    "--code", fetch_code,
    "--session", session
], capture_output=True, text=True, timeout=60)

data = json.loads(result.stdout)
if data.get("ok") and data.get("data", {}).get("value", {}).get("success"):
    base64_content = data["data"]["value"]["base64"]
    pdf_path = "/workspace/01_hypothesis/papers/paper_001.pdf"
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    with open(pdf_path, "wb") as f:
        f.write(base64.b64decode(base64_content))
    print(f"PDF saved: {pdf_path} ({len(base64.b64decode(base64_content))} bytes)")
    
    # Step 3: 提取文本
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join([page.extract_text() or "" for page in pdf.pages])
    print(f"Extracted text length: {len(text)}")
else:
    print(f"Failed to download PDF: {data}")

# Step 4: 关闭 session
subprocess.run([
    "python3", "/workspace/tools/webbridge_client.py", "close",
    "--session", session
], capture_output=True, text=True)
```

---

## 4. 实施计划

### Task 1: 修复 `webbridge_client.py`（P0）

**文件**: `tools/webbridge_client.py`

- [ ] 修复 `fetch` 命令的 `r1.get("success")` → `r1.get("ok") and r1.get("data", {}).get("success")`
- [ ] 增加 `download` 命令（用于 PDF 获取）
- [ ] 测试：`python3 tools/webbridge_client.py fetch --url "https://example.com" --session test`

### Task 2: 重写 Hypothesis SOUL.md（P0）

**文件**: `agent_configs/hypothesis/SOUL.md`

- [ ] 重写工具调用规范部分（对齐 `webbridge_client.py` 实际参数）
- [ ] 增加 Tavily 使用边界限制
- [ ] 增加 DOM 错误恢复策略
- [ ] 增加 PDF 处理策略（方案 A）
- [ ] 增加 Session 管理铁律
- [ ] 删除 `browser` 工具引用
- [ ] 删除矛盾的 `web_extract` 策略

### Task 3: 调整 5 个 Agent 的 Config（P0）

**文件**: `agent_configs/*/config.yaml`

- [ ] 从 `tools.enabled` 中移除 `browser`
- [ ] `terminal.timeout` 从 600 改为 1800
- [ ] `allowed_commands` 中增加 `uv`
- [ ] 保持 `auto_learn: true` 和 `skill_manage`

### Task 4: 调整 Orchestrator（P1）

**文件**: `orchestrator/clients/hermes.py`, `orchestrator/core/orchestrator.py`

- [ ] 默认 `stream=False`
- [ ] 增加各 Agent 的超时配置（hypothesis: 3600s）
- [ ] 增加空结果自动重试逻辑

### Task 5: 启动系统并冒烟测试（P1）

```bash
# 1. 一键纯净启动
bash launch.sh --clean

# 2. 健康检查
python3 -m orchestrator.cli health

# 3. 测试 WebBridge 连通性
docker exec hermes-hypothesis sh -c "python3 /workspace/tools/webbridge_client.py fetch --url https://example.com --session test"

# 4. 测试 data_router
curl http://localhost:8888/health
```

### Task 6: 逐个 Agent 测试（P2）

| 顺序 | Agent | 命令 | 验证标准 |
|------|-------|------|---------|
| 1 | hypothesis | `python3 -m orchestrator.cli run --topic "动量与反转的边界条件" --skip-archive` | 产出 `hypothesis_*.md` + `data_requirements.json` + `references.json` |
| 2 | data_engineer | `--from-stage data_engineer` | 产出 `feature_matrix_*.parquet` + `.agent_checkpoint.json` |
| 3 | quant_analyst | `--from-stage quant_analyst` | 产出 `backtest_results_*.json` + `.agent_checkpoint.json` |
| 4 | risk_auditor | `--from-stage risk_auditor` | 产出 `go_no_go_verdict.md` + `.agent_checkpoint.json` |
| 5 | strategy_writer | `--from-stage strategy_writer` | 产出 `trading_sop_*.md` + `.agent_checkpoint.json` |
| 6 | 端到端 | 清除后完整跑一次 | 5 个 stage 全部 success，HTML 报告生成 |

### Task 7: 整理 Skill 文档（P2）

每个 Agent 成功完成后，整理该 Agent 的**成功工作模式**为 Skill 文档：

1. **quant-cluster-pipeline/SKILL.md** — Kimi Code 如何指挥 5 个 Hermes Agent
2. **quant-hypothesis-researcher/SKILL.md** — Hermes 如何做深度文献调研
3. **quant-data-engineer/SKILL.md** — Hermes 如何做数据工程
4. **quant-backtest-analyst/SKILL.md** — Hermes 如何做回测建模
5. **quant-risk-auditor/SKILL.md** — Hermes 如何做风控审计
6. **quant-strategy-writer/SKILL.md** — Hermes 如何撰写交易 SOP

---

## 5. 测试验收标准

### Hypothesis Agent 验收标准

- [ ] 能正确调用 `web_search` 进行 Tavily 搜索
- [ ] 能正确调用 `webbridge_client.py fetch` 获取网页内容（无 "navigate_error" 误报）
- [ ] 能正确调用 `webbridge_client.py evaluate` 提取页面元素
- [ ] 当 DOM selector 失败时，能切换到兜底策略，不陷入循环
- [ ] 能获取至少 3 个不同信息源的内容
- [ ] 能产出 `hypothesis_*.md`（中英文）
- [ ] 能产出 `data_requirements.json`
- [ ] 能产出 `references.json`
- [ ] 所有 WebBridge session 正确关闭

### Data Engineer Agent 验收标准

- [ ] 能正确读取 `data_requirements.json`
- [ ] 能正确调用 data_router API 获取历史数据
- [ ] 能处理数据缺失情况（3 轮自修复后上报）
- [ ] 能产出 `feature_matrix_*.parquet`
- [ ] 能产出 `.agent_checkpoint.json`

### Pipeline 端到端验收标准

- [ ] 5 个 stage 全部完成，无中断
- [ ] `shared_workspace/archive/{run_id}/` 包含所有报告
- [ ] `final_report.html` 生成成功

---

## 6. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| WebBridge evaluate 返回大 base64 导致超时 | PDF 获取失败 | 限制单页 PDF 大小（<10MB），分批获取 |
| SSRN/QuantConnect 网站结构变化 | DOM selector 失效 | 兜底策略（提取所有 `<p>` 标签）覆盖大部分情况 |
| TWS 未运行或 API 未启用 | data_engineer 无法获取数据 | launch.sh 启动前检查 TWS 状态，给出明确提示 |
| Kimi Code API 不稳定 | Agent 调用失败 | Orchestrator 自动重试机制，非 stream 模式更稳定 |
| hypothesis SOUL.md 过长 | Agent 上下文压力，掉参数 | 精简 SOUL.md，将代码模板提取到外部文件 |

---

## 7. 附录：参考文档

- [原始设计文档](2026-05-15-quant-cluster-hermes-ibkr-design.md)
- [原始实现计划](../plans/2026-05-15-quant-cluster-implementation.md)
- [Quant Cluster Skill](../../../../.kimi/skills/quant-cluster/SKILL.md)
