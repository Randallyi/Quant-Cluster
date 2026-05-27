# Orchestrator Preflight 设计文档

Date: 2026-05-28  
Component: `orchestrator/preflight`  
Source: Fragment Convergence F08 (`docs/insights/convergence-vibe-trading-2026-05-26.md`)  
Status: Approved

---

## 目标

在 Quant Cluster pipeline 启动前执行自动化前置检查，确保基础设施、外部依赖、工作空间全部就绪。**全部绿灯才放行**，任何 fatal 项失败即阻塞 pipeline。

策略原则：
- **orchestrator 能自治解决的，自己解决，不打扰用户**
- **解决不了的（外部依赖未启动），精确报告待办清单**
- **自己的残留进程导致的端口占用，自动 kill，用户无感知**

---

## 架构

### 文件布局

```
orchestrator/
├── preflight.py              # PreflightRunner 主控
├── checks/
│   ├── __init__.py           # 统一导出 + 自动注册
│   ├── base.py               # Check ABC + CheckResult dataclass
│   ├── docker.py             # Docker 容器状态
│   ├── ports.py              # 端口占用 + 残留进程清理
│   ├── api_keys.py           # API key 轻量 ping
│   ├── ibkr.py               # IB Gateway / Data Router 连通性
│   ├── webbridge.py          # WebBridge 可达性
│   ├── hermes_health.py      # 5 个 Hermes Agent HTTP 健康检查
│   └── workspace.py          # Workspace 目录权限
```

### 核心抽象

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class CheckResult:
    name: str
    passed: bool
    category: str              # "infra" | "external" | "workspace"
    severity: str              # "fatal" | "warning"
    message: str
    fix_attempted: bool        # orchestrator 是否尝试过修复
    fix_success: bool          # 修复是否成功（仅 fix_attempted=True 时有效）
    todo: str | None           # 用户待办动作（未通过时必填）

class Check(ABC):
    name: str
    category: str
    auto_fixable: bool         # True = orchestrator 会尝试修复
    severity: str              # "fatal" | "warning"

    @abstractmethod
    async def run(self) -> CheckResult: ...
```

### 注册表

`checks/__init__.py` 在导入时收集所有 `Check` 子类：

```python
_CHECK_REGISTRY: dict[str, type[Check]] = {}

def register(cls: type[Check]) -> type[Check]:
    _CHECK_REGISTRY[cls.name] = cls
    return cls

# 子类示例
@register
class DockerContainersCheck(Check):
    name = "docker_containers"
    category = "infra"
    auto_fixable = True
    severity = "fatal"
    ...
```

---

## 检查项详单

| 检查项 | 模块 | Category | Auto-fixable | Severity | 自愈动作 |
|--------|------|----------|--------------|----------|----------|
| Docker 6 容器运行 | `docker.py` | infra | ✅ Yes | fatal | `docker compose up -d` 缺失容器 |
| 端口占用 | `ports.py` | infra | ✅ Yes | fatal | 识别 quant-cluster 残留进程 → `kill`；清理后重试 |
| API Key 有效性 | `api_keys.py` | infra | ❌ No | fatal | 无自愈，报告缺失/失效的 key |
| Hermes Health | `hermes_health.py` | infra | ❌ No | fatal | 5 个 Agent HTTP /health 全部 200 |
| IB Gateway | `ibkr.py` | external | ❌ No | fatal | 报告 TWS 未启动或 7497 不通 |
| Data Router | `ibkr.py` | external | ❌ No | fatal | 报告 Data Router 未就绪 |
| WebBridge | `webbridge.py` | external | ❌ No | fatal | 报告 WebBridge 未在 10086 监听 |
| Workspace 权限 | `workspace.py` | workspace | ✅ Yes | fatal | `mkdir -p` 缺失目录；`chmod` 修复权限 |

### 端口占用自愈策略（关键决策）

`ports.py` 的 `PortCheck` 对期望端口列表（8642–8646, 8888, 10086, 8080）逐个检查：

1. **端口空闲** → PASS
2. **端口被占用** → 通过 `lsof -Pi :{port}` 获取 PID
3. **进程归属判定**：
   - 进程名匹配 quant-cluster 相关（`docker`, `python.*hermes`, `python.*webbridge`, `uvicorn` 且 cwd 在项目目录下）→ **自动 `kill -9 {pid}`**，等待 2 秒后重检
   - 进程不属于自己的残留 → 视为 fatal，报告 `"端口 {port} 被外部进程 {name}[{pid}] 占用，请手动释放"`
4. **kill 后仍被占** → fatal，报告 `"尝试清理端口 {port} 失败，请手动检查"`

---

## 执行流程

```
PreflightRunner.run_all()
│
├── Phase 1: 自愈轮
│   └── 只跑 auto_fixable=True 的 Check
│       ├── 通过 → 记录 PASS
│       └── 未通过 → 尝试修复 → 记录 fix_attempted + fix_success
│
├── Phase 2: 验证轮
│   └── 对 Phase 1 中 fix_attempted=True 的项重新 run
│       ├── fix_success=True 且现在通过 → PASS
│       └── 仍不通过 → FAIL（fatal）
│
├── Phase 3: 报告轮
│   └── 跑 auto_fixable=False 的 Check
│       └── 任一 fatal 未通过 → 整体阻塞
│
└── 最终判定
    ├── 全部 fatal PASS → 🟢 放行，返回 exit 0
    └── 任一 fatal FAIL → 🔴 阻塞，输出待办清单，返回 exit 1
```

---

## 集成点

### 1. `launch.sh`（启动时）

替换现有第 6 步：

```bash
# 原有手工检查保留作为快速失败（不依赖 Python 环境）
# 真正准入判定交给 preflight

echo "🔍 运行 Preflight 前置检查..."
python3 -m orchestrator.preflight --mode=launch
# exit code 0 = 全部通过, 非 0 = 阻塞并输出报告
```

- Preflight 失败时，`launch.sh` 直接 `exit 1`，不进入后续步骤
- `--mode=launch` 表示由启动脚本调用，输出更简洁（无 Rich 动画）

### 2. `cli.py health`（手动诊断）

```python
async def cmd_health(orch: InteractiveOrchestrator):
    from orchestrator.preflight import PreflightRunner
    runner = PreflightRunner()
    report = await runner.run_all()
    report.print_table()
    if not report.all_passed:
        console.print("[red]🔴 Preflight 未通过，请修复上述问题后再运行 pipeline[/red]")
    sys.exit(0 if report.all_passed else 1)
```

- 原有 `orch.health_check_all()`（5 个 Hermes HTTP ping）降级为 preflight 的子检查项 `HermesHealthCheck`
- `cli health` = 完整 preflight 全量检查

### 3. `run_pipeline`（运行时拦截）

在 `InteractiveOrchestrator.run_pipeline()` 开头增加 preflight gate：

```python
async def run_pipeline(self, topic, stream=False, dry_run=False, skip_archive=False):
    # ── Preflight gate ──
    if not dry_run and not getattr(self, "_skip_preflight", False):
        from orchestrator.preflight import PreflightRunner
        runner = PreflightRunner()
        report = await runner.run_all()
        if not report.all_passed:
            report.print_table()
            console.rule("[bold red]🔴 Preflight 检查未通过，pipeline 已阻止")
            return {
                "status": "failed",
                "reason": "preflight_failed",
                "report": report.to_dict(),
            }
    # ── 原有 pipeline 逻辑 ──
```

- `--dry-run` 自动跳过 preflight（不会调 agent，无需检查基础设施）
- 新增 `--skip-preflight` CLI flag（应急用途）

---

## 输出格式

### 终端 Rich 表格

```
🔍 Quant Cluster Preflight Report
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Check               ┃ Status   ┃ Category    ┃ Message / Action                 ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Docker Containers   │ ✅ PASS  │ infra       │ 6/6 容器运行中                   │
│ Port Availability   │ ✅ PASS  │ infra       │ 已清理 1 个残留进程，端口可用    │
│ API Keys            │ ✅ PASS  │ infra       │ 所有 key 有效                    │
│ Hermes Health       │ ✅ PASS  │ infra       │ 5/5 Agent 响应正常               │
│ IB Gateway          │ ✅ PASS  │ external    │ TWS 端口 7497 连通               │
│ Data Router         │ ✅ PASS  │ external    │ localhost:8888/health 200        │
│ WebBridge           │ ✅ PASS  │ external    │ port 10086 响应正常              │
│ Workspace           │ ✅ PASS  │ workspace   │ 目录结构完整，权限正常           │
└─────────────────────┴──────────┴─────────────┴──────────────────────────────────┘
🟢 All checks passed. Ready to launch.
```

失败示例：
```
🔴 2 fatal failures detected. Pipeline blocked.

💡 待办清单：
  1. [IB Gateway] 请启动 IB Gateway 并配置 Trusted IP: 192.168.65.0/24
     下载地址: https://www.interactivebrokers.com/en/index.php?f=16457
  2. [WebBridge] 请启动 WebBridge 服务:
     python3 -m webbridge.server
```

### 结构化 JSON（`--json` flag）

```json
{
  "passed": false,
  "all_fatal_passed": false,
  "checks": [
    {
      "name": "ib_gateway",
      "passed": false,
      "category": "external",
      "severity": "fatal",
      "message": "TWS 端口 7497 无响应",
      "fix_attempted": false,
      "fix_success": false,
      "todo": "请启动 IB Gateway 并配置 Trusted IP: 192.168.65.0/24"
    }
  ],
  "fatal_count": 1,
  "warning_count": 0,
  "fix_attempted_count": 0,
  "todo_list": [
    {
      "check": "ib_gateway",
      "action": "启动 IB Gateway",
      "detail": "配置 Trusted IP: 192.168.65.0/24",
      "reference_url": "https://www.interactivebrokers.com/en/index.php?f=16457"
    }
  ]
}
```

---

## 扩展机制

新增检查项的成本 = 1 个文件，零侵入核心：

```python
# orchestrator/checks/example.py
from orchestrator.checks.base import Check, CheckResult
from orchestrator.checks import register

@register
class ExampleCheck(Check):
    name = "example"
    category = "infra"
    auto_fixable = False
    severity = "fatal"

    async def run(self) -> CheckResult:
        ok = True  # 实际检查逻辑
        return CheckResult(
            name=self.name,
            passed=ok,
            category=self.category,
            severity=self.severity,
            message="示例检查通过" if ok else "示例检查失败",
            fix_attempted=False,
            fix_success=False,
            todo=None if ok else "请修复示例问题",
        )
```

`checks/__init__.py` 通过 `pkgutil.iter_modules()` 自动导入所有子模块完成注册，无需手动导入新文件。

---

## 不做的事项

| 事项 | 原因 |
|------|------|
| 交互式 `quant-cluster init` CLI | 用户明确要求不做 |
| 非量化相关的外部服务检查 | 只检查 pipeline 直接依赖 |
| 自动下载/安装缺失软件（如 Docker Desktop） | 超出 orchestrator 权限范围 |
| 定时/后台健康监控 | preflight 是**启动前一次性检查**，非常驻守护 |

---

## 验证检查清单

- [ ] `orchestrator/checks/` 下 8 个模块全部实现
- [ ] `launch.sh` 集成 preflight 并阻塞失败场景
- [ ] `cli.py health` 调用 preflight 全量检查
- [ ] `run_pipeline` 前置拦截 gate 生效
- [ ] `--skip-preflight` flag 生效
- [ ] `--json` flag 输出合法 JSON
- [ ] 残留进程自动 kill 逻辑有单元测试（mock `os.kill`）
- [ ] 新增检查项可通过单文件扩展，无需改 `preflight.py`
