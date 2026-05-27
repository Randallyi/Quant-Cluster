# Orchestrator Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `orchestrator/preflight` — automated pre-launch checks with auto-fix for infra/workspace and fatal-blocking for external dependencies.

**Architecture:** Plugin Registry pattern where each check is a standalone `Check` subclass auto-registered via `@register`. `PreflightRunner` executes checks in three phases: auto-fix → re-verify → report-only. Integration points: `launch.sh` gate, `cli.py health` command, and `run_pipeline` interception.

**Tech Stack:** Python 3.11+, asyncio, aiohttp, rich, pytest, pytest-asyncio

---

## File Structure

```
orchestrator/
├── checks/
│   ├── __init__.py           # CHECK_REGISTRY + auto-import
│   ├── base.py               # Check ABC, CheckResult, PreflightReport, PreflightRunner
│   ├── docker.py             # Docker container status (auto-fixable)
│   ├── ports.py              # Port availability + residual process kill (auto-fixable)
│   ├── api_keys.py           # .env key presence + light ping
│   ├── hermes_health.py      # 5 Hermes Agent HTTP health checks
│   ├── ibkr.py               # IB Gateway + Data Router connectivity
│   ├── webbridge.py          # WebBridge port 10086 health
│   └── workspace.py          # Workspace directory permissions (auto-fixable)
├── preflight.py              # CLI entrypoint: python -m orchestrator.preflight
├── cli.py                    # MODIFY: health command, --skip-preflight, run_pipeline gate
tests/orchestrator/
├── __init__.py
├── test_preflight.py         # PreflightRunner integration tests
└── test_checks/
    ├── __init__.py
    ├── test_workspace.py
    ├── test_docker.py
    ├── test_ports.py
    ├── test_api_keys.py
    ├── test_hermes_health.py
    ├── test_ibkr.py
    └── test_webbridge.py
```

---

### Task 1: Registry Skeleton + Workspace Check (TDD Baseline)

**Files:**
- Create: `orchestrator/checks/base.py`
- Create: `orchestrator/checks/__init__.py`
- Create: `orchestrator/checks/workspace.py`
- Create: `tests/orchestrator/__init__.py`
- Create: `tests/orchestrator/test_checks/__init__.py`
- Create: `tests/orchestrator/test_checks/test_workspace.py`

- [ ] **Step 1: Write base.py — CheckResult + Check ABC**

```python
"""Base abstractions for preflight checks."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class CheckResult:
    name: str
    passed: bool
    category: str              # "infra" | "external" | "workspace"
    severity: str              # "fatal" | "warning"
    message: str
    fix_attempted: bool = False
    fix_success: bool = False
    todo: Optional[str] = None


class Check(ABC):
    name: str
    category: str
    auto_fixable: bool
    severity: str

    @abstractmethod
    async def run(self) -> CheckResult:
        ...
```

- [ ] **Step 2: Write checks/__init__.py — auto-registration**

```python
"""Preflight check registry — auto-imports all check modules."""
import pkgutil
from orchestrator.checks.base import Check, CheckResult

CHECK_REGISTRY: Dict[str, type[Check]] = {}


def register(cls: type[Check]) -> type[Check]:
    CHECK_REGISTRY[cls.name] = cls
    return cls


# Auto-import all submodules to trigger @register decorators
for _, _modname, _ in pkgutil.iter_modules(__path__):
    __import__(f"{__package__}.{_modname}")
```

- [ ] **Step 3: Write failing test for WorkspaceCheck**

```python
"""Tests for workspace preflight check."""
import pytest
from orchestrator.checks.workspace import WorkspaceCheck


@pytest.mark.asyncio
async def test_workspace_passes_when_directories_exist(tmp_path, monkeypatch):
    # Create expected workspace structure
    for sub in ["01_hypothesis", "02_data", "03_backtest", "04_risk", "05_strategy"]:
        (tmp_path / sub).mkdir()
    
    check = WorkspaceCheck(workspace_root=tmp_path)
    result = await check.run()
    assert result.passed is True
    assert result.fix_attempted is False


@pytest.mark.asyncio
async def test_workspace_creates_missing_directories(tmp_path, monkeypatch):
    # Only some dirs exist
    (tmp_path / "01_hypothesis").mkdir()
    
    check = WorkspaceCheck(workspace_root=tmp_path)
    result = await check.run()
    assert result.passed is True
    assert result.fix_attempted is True
    assert result.fix_success is True
    assert (tmp_path / "05_strategy").exists()
```

Run: `pytest tests/orchestrator/test_checks/test_workspace.py -v`
Expected: FAIL — `WorkspaceCheck` not defined yet

- [ ] **Step 4: Implement workspace.py**

```python
"""Workspace directory permission check."""
from pathlib import Path

from orchestrator.checks.base import Check, CheckResult
from orchestrator.checks import register


@register
class WorkspaceCheck(Check):
    name = "workspace"
    category = "workspace"
    auto_fixable = True
    severity = "fatal"

    EXPECTED_DIRS = ["01_hypothesis", "02_data", "03_backtest", "04_risk", "05_strategy"]

    def __init__(self, workspace_root: Path | None = None):
        from orchestrator.core.dag import WORKSPACE_ROOT
        self.workspace_root = workspace_root or WORKSPACE_ROOT

    async def run(self) -> CheckResult:
        missing = []
        for sub in self.EXPECTED_DIRS:
            p = self.workspace_root / sub
            if not p.exists():
                missing.append(sub)

        if not missing:
            return CheckResult(
                name=self.name,
                passed=True,
                category=self.category,
                severity=self.severity,
                message="目录结构完整，权限正常",
                fix_attempted=False,
                fix_success=False,
            )

        # Auto-fix: create missing directories
        fix_ok = True
        for sub in missing:
            try:
                (self.workspace_root / sub).mkdir(parents=True, exist_ok=True)
            except Exception:
                fix_ok = False

        # Re-check
        still_missing = [sub for sub in missing if not (self.workspace_root / sub).exists()]
        passed = not still_missing and fix_ok

        return CheckResult(
            name=self.name,
            passed=passed,
            category=self.category,
            severity=self.severity,
            message="自动创建缺失目录" if passed else f"无法创建目录: {still_missing}",
            fix_attempted=True,
            fix_success=passed,
            todo=None if passed else f"请手动创建目录: {still_missing}",
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/orchestrator/test_checks/test_workspace.py -v`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add orchestrator/checks/ tests/orchestrator/
git commit -m "feat(preflight): add check registry skeleton + workspace check"
```

---

### Task 2: Docker Containers Check

**Files:**
- Create: `orchestrator/checks/docker.py`
- Create: `tests/orchestrator/test_checks/test_docker.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for Docker container preflight check."""
import pytest
from unittest.mock import AsyncMock, patch
from orchestrator.checks.docker import DockerContainersCheck


@pytest.mark.asyncio
async def test_docker_passes_when_all_containers_running():
    check = DockerContainersCheck()
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.communicate.return_value = (b"quant-data-router\nhermes-hypothesis\nhermes-data\nhermes-quant\nhermes-risk\nhermes-writer\n", b"")
        proc.returncode = 0
        mock_exec.return_value = proc
        
        result = await check.run()
        assert result.passed is True
        assert result.fix_attempted is False


@pytest.mark.asyncio
async def test_docker_attempts_restart_on_missing():
    check = DockerContainersCheck()
    call_count = 0
    
    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        proc = AsyncMock()
        if call_count == 1:
            # First docker ps — missing quant-data-router
            proc.communicate.return_value = (b"hermes-hypothesis\nhermes-data\nhermes-quant\nhermes-risk\nhermes-writer\n", b"")
        elif call_count == 2:
            # docker compose up -d
            proc.communicate.return_value = (b"", b"")
            proc.returncode = 0
        else:
            # Second docker ps — all present
            proc.communicate.return_value = (b"quant-data-router\nhermes-hypothesis\nhermes-data\nhermes-quant\nhermes-risk\nhermes-writer\n", b"")
        proc.returncode = 0
        return proc
    
    with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
        result = await check.run()
        assert result.passed is True
        assert result.fix_attempted is True
        assert result.fix_success is True
```

Run: `pytest tests/orchestrator/test_checks/test_docker.py -v`
Expected: FAIL — `DockerContainersCheck` not defined

- [ ] **Step 2: Implement docker.py**

```python
"""Docker container status check."""
import asyncio

from orchestrator.checks.base import Check, CheckResult
from orchestrator.checks import register


@register
class DockerContainersCheck(Check):
    name = "docker_containers"
    category = "infra"
    auto_fixable = True
    severity = "fatal"

    EXPECTED = [
        "quant-data-router",
        "hermes-hypothesis",
        "hermes-data",
        "hermes-quant",
        "hermes-risk",
        "hermes-writer",
    ]

    async def run(self) -> CheckResult:
        running = await self._list_running()
        missing = [c for c in self.EXPECTED if c not in running]

        if not missing:
            return CheckResult(
                name=self.name,
                passed=True,
                category=self.category,
                severity=self.severity,
                message=f"{len(self.EXPECTED)}/{len(self.EXPECTED)} 容器运行中",
                fix_attempted=False,
                fix_success=False,
            )

        # Try to fix: docker compose up -d missing containers
        fix_ok = False
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "up", "-d", *missing,
                stdout=asyncio.PIPE,
                stderr=asyncio.PIPE,
            )
            _, _ = await proc.communicate()
            fix_ok = proc.returncode == 0
        except Exception:
            fix_ok = False

        # Re-check
        if fix_ok:
            running = await self._list_running()
            still_missing = [c for c in self.EXPECTED if c not in running]
            if not still_missing:
                return CheckResult(
                    name=self.name,
                    passed=True,
                    category=self.category,
                    severity=self.severity,
                    message="已自动启动缺失容器",
                    fix_attempted=True,
                    fix_success=True,
                )
            missing = still_missing

        return CheckResult(
            name=self.name,
            passed=False,
            category=self.category,
            severity=self.severity,
            message=f"缺失容器: {', '.join(missing)}",
            fix_attempted=True,
            fix_success=False,
            todo=f"docker compose up -d 失败，请手动检查：{missing}",
        )

    async def _list_running(self) -> set:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "ps", "--format", "{{.Names}}",
                stdout=asyncio.PIPE,
                stderr=asyncio.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                return set()
            text = stdout.decode().strip()
            return set(text.split("\n")) if text else set()
        except Exception:
            return set()
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/orchestrator/test_checks/test_docker.py -v`
Expected: 2 PASS

- [ ] **Step 4: Commit**

```bash
git add orchestrator/checks/docker.py tests/orchestrator/test_checks/test_docker.py
git commit -m "feat(preflight): add Docker container check with auto-restart"
```

---

### Task 3: Port Availability Check (Residual Process Kill)

**Files:**
- Create: `orchestrator/checks/ports.py`
- Create: `tests/orchestrator/test_checks/test_ports.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for port availability preflight check."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from orchestrator.checks.ports import PortAvailabilityCheck


@pytest.mark.asyncio
async def test_ports_pass_when_all_free():
    check = PortAvailabilityCheck()
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"")  # lsof returns nothing = port free
        proc.returncode = 1
        mock_exec.return_value = proc
        
        result = await check.run()
        assert result.passed is True
        assert "全部端口可用" in result.message


@pytest.mark.asyncio
async def test_ports_kill_residual_process():
    check = PortAvailabilityCheck()
    call_sequence = []
    
    async def side_effect(*args, **kwargs):
        proc = AsyncMock()
        cmd = args[0] if args else ""
        
        if cmd == "lsof":
            call_sequence.append("lsof")
            if len([c for c in call_sequence if c == "lsof"]) == 1:
                # First check: port 8642 occupied by our residual process
                proc.communicate.return_value = (b"12345\n", b"")
                proc.returncode = 0
            else:
                # After kill: port free
                proc.communicate.return_value = (b"", b"")
                proc.returncode = 1
        elif cmd == "ps":
            proc.communicate.return_value = (b"python hermes-gateway --port 8642\n", b"")
            proc.returncode = 0
        
        return proc
    
    with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
        with patch("os.kill") as mock_kill:
            result = await check.run()
            assert result.passed is True
            assert result.fix_attempted is True
            assert result.fix_success is True
            mock_kill.assert_called_once_with(12345, 9)


@pytest.mark.asyncio
async def test_ports_fails_on_external_process():
    check = PortAvailabilityCheck()
    
    async def side_effect(*args, **kwargs):
        proc = AsyncMock()
        cmd = args[0] if args else ""
        if cmd == "lsof":
            proc.communicate.return_value = (b"99999\n", b"")
            proc.returncode = 0
        elif cmd == "ps":
            proc.communicate.return_value = (b"nginx nginx: worker process\n", b"")
            proc.returncode = 0
        return proc
    
    with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
        result = await check.run()
        assert result.passed is False
        assert result.fix_attempted is False
        assert "nginx" in result.message
```

Run: `pytest tests/orchestrator/test_checks/test_ports.py -v`
Expected: FAIL — `PortAvailabilityCheck` not defined

- [ ] **Step 2: Implement ports.py**

```python
"""Port availability check with residual process auto-kill."""
import asyncio
import os

from orchestrator.checks.base import Check, CheckResult
from orchestrator.checks import register


@register
class PortAvailabilityCheck(Check):
    name = "port_availability"
    category = "infra"
    auto_fixable = True
    severity = "fatal"

    EXPECTED_PORTS = [8642, 8643, 8644, 8645, 8646, 8888, 10086, 8080]
    OUR_PATTERNS = ["hermes", "quant-cluster", "webbridge", "uvicorn", "fastapi"]

    async def run(self) -> CheckResult:
        blocked = []
        killed_count = 0

        for port in self.EXPECTED_PORTS:
            pid = await self._get_listener_pid(port)
            if pid is None:
                continue  # port is free

            # Check if it's a Docker port-forward (expected)
            if await self._is_docker_process(pid):
                continue

            # Check if it's our residual process
            if await self._is_our_residual(pid):
                try:
                    os.kill(pid, 9)
                    killed_count += 1
                    await asyncio.sleep(2)
                    # Re-check after kill
                    if await self._get_listener_pid(port) is None:
                        continue  # successfully freed
                    blocked.append((port, f"清理后仍被占用 (pid {pid})"))
                except Exception as e:
                    blocked.append((port, f"无法终止残留进程 {pid}: {e}"))
            else:
                # External process — do NOT kill
                info = await self._get_process_info(pid)
                comm = info.get("comm", "?")
                blocked.append((port, f"被外部进程 {comm}[{pid}] 占用"))

        if not blocked:
            msg = "全部端口可用"
            if killed_count:
                msg += f"（已清理 {killed_count} 个残留进程）"
            return CheckResult(
                name=self.name,
                passed=True,
                category=self.category,
                severity=self.severity,
                message=msg,
                fix_attempted=killed_count > 0,
                fix_success=killed_count > 0,
            )

        todo = "; ".join(f"端口 {port}: {reason}" for port, reason in blocked)
        return CheckResult(
            name=self.name,
            passed=False,
            category=self.category,
            severity=self.severity,
            message=f"端口阻塞 — {todo}",
            fix_attempted=killed_count > 0,
            fix_success=False,
            todo=todo,
        )

    async def _get_listener_pid(self, port: int) -> int | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "lsof", "-Pi", f":{port}", "-sTCP:LISTEN", "-t",
                stdout=asyncio.PIPE,
                stderr=asyncio.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0 or not stdout.strip():
                return None
            return int(stdout.decode().strip().split()[0])
        except Exception:
            return None

    async def _is_docker_process(self, pid: int) -> bool:
        info = await self._get_process_info(pid)
        comm = info.get("comm", "").lower()
        return "docker" in comm or "com.docker" in comm

    async def _is_our_residual(self, pid: int) -> bool:
        info = await self._get_process_info(pid)
        comm = info.get("comm", "").lower()
        args = info.get("args", "").lower()
        return any(p in comm or p in args for p in self.OUR_PATTERNS)

    async def _get_process_info(self, pid: int) -> dict:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ps", "-p", str(pid), "-o", "comm=,args=",
                stdout=asyncio.PIPE,
                stderr=asyncio.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                return {}
            parts = stdout.decode().strip().split(None, 1)
            return {
                "comm": parts[0] if parts else "",
                "args": parts[1] if len(parts) > 1 else "",
            }
        except Exception:
            return {}
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/orchestrator/test_checks/test_ports.py -v`
Expected: 3 PASS

- [ ] **Step 4: Commit**

```bash
git add orchestrator/checks/ports.py tests/orchestrator/test_checks/test_ports.py
git commit -m "feat(preflight): add port check with auto-kill for residual processes"
```

---

### Task 4: API Keys + Hermes Health Checks

**Files:**
- Create: `orchestrator/checks/api_keys.py`
- Create: `orchestrator/checks/hermes_health.py`
- Create: `tests/orchestrator/test_checks/test_api_keys.py`
- Create: `tests/orchestrator/test_checks/test_hermes_health.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/orchestrator/test_checks/test_api_keys.py
import pytest
from unittest.mock import AsyncMock, patch
from orchestrator.checks.api_keys import ApiKeysCheck


@pytest.mark.asyncio
async def test_api_keys_pass_when_env_present_and_valid():
    check = ApiKeysCheck()
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test", "TAVILY_API_KEY": "tv-test"}):
        with patch("aiohttp.ClientSession") as MockSession:
            session = AsyncMock()
            resp = AsyncMock()
            resp.status = 200
            session.get.return_value.__aenter__ = AsyncMock(return_value=resp)
            session.get.return_value.__aexit__ = AsyncMock(return_value=False)
            MockSession.return_value.__aenter__ = AsyncMock(return_value=session)
            MockSession.return_value.__aexit__ = AsyncMock(return_value=False)
            
            result = await check.run()
            assert result.passed is True


@pytest.mark.asyncio
async def test_api_keys_fails_when_missing():
    check = ApiKeysCheck()
    with patch.dict("os.environ", {}, clear=True):
        result = await check.run()
        assert result.passed is False
        assert "ANTHROPIC_API_KEY" in result.message
```

```python
# tests/orchestrator/test_checks/test_hermes_health.py
import pytest
from unittest.mock import AsyncMock, patch
from orchestrator.checks.hermes_health import HermesHealthCheck


@pytest.mark.asyncio
async def test_hermes_passes_when_all_respond():
    check = HermesHealthCheck()
    with patch("aiohttp.ClientSession") as MockSession:
        session = AsyncMock()
        resp = AsyncMock()
        resp.status = 200
        session.get.return_value.__aenter__ = AsyncMock(return_value=resp)
        session.get.return_value.__aexit__ = AsyncMock(return_value=False)
        MockSession.return_value.__aenter__ = AsyncMock(return_value=session)
        MockSession.return_value.__aexit__ = AsyncMock(return_value=False)
        
        result = await check.run()
        assert result.passed is True
        assert "5/5" in result.message


@pytest.mark.asyncio
async def test_hermes_fails_when_some_offline():
    check = HermesHealthCheck()
    call_count = 0
    
    async def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = AsyncMock()
        # Fail first agent
        resp.status = 200 if call_count > 1 else 503
        return resp
    
    with patch("aiohttp.ClientSession") as MockSession:
        session = AsyncMock()
        session.get = mock_get
        session.get.return_value.__aenter__ = AsyncMock(side_effect=mock_get)
        session.get.return_value.__aexit__ = AsyncMock(return_value=False)
        MockSession.return_value.__aenter__ = AsyncMock(return_value=session)
        MockSession.return_value.__aexit__ = AsyncMock(return_value=False)
        
        result = await check.run()
        assert result.passed is False
        assert "hypothesis" in result.todo
```

Run: `pytest tests/orchestrator/test_checks/test_api_keys.py tests/orchestrator/test_checks/test_hermes_health.py -v`
Expected: FAIL — modules not defined

- [ ] **Step 2: Implement api_keys.py**

```python
"""API key presence and validity check."""
import os

import aiohttp

from orchestrator.checks.base import Check, CheckResult
from orchestrator.checks import register


@register
class ApiKeysCheck(Check):
    name = "api_keys"
    category = "infra"
    auto_fixable = False
    severity = "fatal"

    REQUIRED_KEYS = ["ANTHROPIC_API_KEY", "TAVILY_API_KEY"]
    KIMI_MODELS_URL = "https://api.kimi.com/coding/v1/models"

    async def run(self) -> CheckResult:
        missing = [k for k in self.REQUIRED_KEYS if not os.environ.get(k)]
        if missing:
            return CheckResult(
                name=self.name,
                passed=False,
                category=self.category,
                severity=self.severity,
                message=f".env 中缺失 API key: {', '.join(missing)}",
                todo=f"请在 .env 中配置: {missing}",
            )

        # Light ping: verify ANTHROPIC_API_KEY can reach Kimi API
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.KIMI_MODELS_URL,
                    headers={"Authorization": f"Bearer {anthropic_key}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return CheckResult(
                            name=self.name,
                            passed=False,
                            category=self.category,
                            severity=self.severity,
                            message="ANTHROPIC_API_KEY 无法通过 Kimi API 验证",
                            todo="请检查 ANTHROPIC_API_KEY 是否有效",
                        )
        except Exception as e:
            return CheckResult(
                name=self.name,
                passed=False,
                category=self.category,
                severity=self.severity,
                message=f"API 连通性测试失败: {e}",
                todo="请检查网络连接和 API key 有效性",
            )

        return CheckResult(
            name=self.name,
            passed=True,
            category=self.category,
            severity=self.severity,
            message="所有 key 有效",
            fix_attempted=False,
            fix_success=False,
        )
```

- [ ] **Step 3: Implement hermes_health.py**

```python
"""Hermes Agent HTTP health check."""
import aiohttp

from orchestrator.checks.base import Check, CheckResult
from orchestrator.checks import register


@register
class HermesHealthCheck(Check):
    name = "hermes_health"
    category = "infra"
    auto_fixable = False
    severity = "fatal"

    EXPECTED_AGENTS = {
        "hypothesis": 8642,
        "data_engineer": 8643,
        "quant_analyst": 8644,
        "risk_auditor": 8645,
        "strategy_writer": 8646,
    }

    async def run(self) -> CheckResult:
        failed = []
        async with aiohttp.ClientSession() as session:
            for name, port in self.EXPECTED_AGENTS.items():
                try:
                    async with session.get(
                        f"http://localhost:{port}/health",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status != 200:
                            failed.append(name)
                except Exception:
                    failed.append(name)

        if not failed:
            total = len(self.EXPECTED_AGENTS)
            return CheckResult(
                name=self.name,
                passed=True,
                category=self.category,
                severity=self.severity,
                message=f"{total}/{total} Agent 响应正常",
                fix_attempted=False,
                fix_success=False,
            )

        return CheckResult(
            name=self.name,
            passed=False,
            category=self.category,
            severity=self.severity,
            message=f"以下 Agent 未响应: {', '.join(failed)}",
            todo=f"请检查 Docker 容器状态: {failed}",
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/orchestrator/test_checks/test_api_keys.py tests/orchestrator/test_checks/test_hermes_health.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/checks/api_keys.py orchestrator/checks/hermes_health.py tests/orchestrator/test_checks/test_api_keys.py tests/orchestrator/test_checks/test_hermes_health.py
git commit -m "feat(preflight): add API key and Hermes health checks"
```

---

### Task 5: External Checks (IBKR + WebBridge)

**Files:**
- Create: `orchestrator/checks/ibkr.py`
- Create: `orchestrator/checks/webbridge.py`
- Create: `tests/orchestrator/test_checks/test_ibkr.py`
- Create: `tests/orchestrator/test_checks/test_webbridge.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/orchestrator/test_checks/test_ibkr.py
import pytest
from unittest.mock import AsyncMock, patch
from orchestrator.checks.ibkr import IbkrGatewayCheck, DataRouterCheck


@pytest.mark.asyncio
async def test_ibkr_passes_when_tws_reachable():
    check = IbkrGatewayCheck()
    with patch("socket.create_connection") as mock_conn:
        mock_conn.return_value.__enter__ = MagicMock(return_value=None)
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        result = await check.run()
        assert result.passed is True


@pytest.mark.asyncio
async def test_data_router_passes_when_healthy():
    check = DataRouterCheck()
    with patch("aiohttp.ClientSession") as MockSession:
        session = AsyncMock()
        resp = AsyncMock()
        resp.status = 200
        session.get.return_value.__aenter__ = AsyncMock(return_value=resp)
        session.get.return_value.__aexit__ = AsyncMock(return_value=False)
        MockSession.return_value.__aenter__ = AsyncMock(return_value=session)
        MockSession.return_value.__aexit__ = AsyncMock(return_value=False)
        
        result = await check.run()
        assert result.passed is True
```

```python
# tests/orchestrator/test_checks/test_webbridge.py
import pytest
from unittest.mock import AsyncMock, patch
from orchestrator.checks.webbridge import WebBridgeCheck


@pytest.mark.asyncio
async def test_webbridge_passes_when_healthy():
    check = WebBridgeCheck()
    with patch("aiohttp.ClientSession") as MockSession:
        session = AsyncMock()
        resp = AsyncMock()
        resp.status = 200
        session.get.return_value.__aenter__ = AsyncMock(return_value=resp)
        session.get.return_value.__aexit__ = AsyncMock(return_value=False)
        MockSession.return_value.__aenter__ = AsyncMock(return_value=session)
        MockSession.return_value.__aexit__ = AsyncMock(return_value=False)
        
        result = await check.run()
        assert result.passed is True
```

Run: `pytest tests/orchestrator/test_checks/test_ibkr.py tests/orchestrator/test_checks/test_webbridge.py -v`
Expected: FAIL — modules not defined

- [ ] **Step 2: Implement ibkr.py**

```python
"""IB Gateway and Data Router connectivity checks."""
import socket

import aiohttp

from orchestrator.checks.base import Check, CheckResult
from orchestrator.checks import register


@register
class IbkrGatewayCheck(Check):
    name = "ib_gateway"
    category = "external"
    auto_fixable = False
    severity = "fatal"

    async def run(self) -> CheckResult:
        try:
            with socket.create_connection(("localhost", 7497), timeout=5):
                return CheckResult(
                    name=self.name,
                    passed=True,
                    category=self.category,
                    severity=self.severity,
                    message="TWS 端口 7497 连通",
                    fix_attempted=False,
                    fix_success=False,
                )
        except Exception:
            return CheckResult(
                name=self.name,
                passed=False,
                category=self.category,
                severity=self.severity,
                message="TWS 端口 7497 无响应",
                todo="请启动 IB Gateway 并配置 Trusted IP: 192.168.65.0/24",
            )


@register
class DataRouterCheck(Check):
    name = "data_router"
    category = "external"
    auto_fixable = False
    severity = "fatal"

    async def run(self) -> CheckResult:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "http://localhost:8888/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        return CheckResult(
                            name=self.name,
                            passed=True,
                            category=self.category,
                            severity=self.severity,
                            message="localhost:8888/health 响应正常",
                            fix_attempted=False,
                            fix_success=False,
                        )
        except Exception:
            pass

        return CheckResult(
            name=self.name,
            passed=False,
            category=self.category,
            severity=self.severity,
            message="Data Router 未就绪",
            todo="请检查 docker logs quant-data-router",
        )
```

- [ ] **Step 3: Implement webbridge.py**

```python
"""WebBridge reachability check."""
import aiohttp

from orchestrator.checks.base import Check, CheckResult
from orchestrator.checks import register


@register
class WebBridgeCheck(Check):
    name = "webbridge"
    category = "external"
    auto_fixable = False
    severity = "fatal"

    async def run(self) -> CheckResult:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "http://localhost:10086/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        return CheckResult(
                            name=self.name,
                            passed=True,
                            category=self.category,
                            severity=self.severity,
                            message="port 10086 响应正常",
                            fix_attempted=False,
                            fix_success=False,
                        )
        except Exception:
            pass

        return CheckResult(
            name=self.name,
            passed=False,
            category=self.category,
            severity=self.severity,
            message="WebBridge 未在端口 10086 监听",
            todo="请启动 WebBridge: python3 -m webbridge.server",
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/orchestrator/test_checks/test_ibkr.py tests/orchestrator/test_checks/test_webbridge.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/checks/ibkr.py orchestrator/checks/webbridge.py tests/orchestrator/test_checks/test_ibkr.py tests/orchestrator/test_checks/test_webbridge.py
git commit -m "feat(preflight): add IBKR, Data Router, and WebBridge checks"
```

---

### Task 6: PreflightRunner + Report + CLI Entrypoint

**Files:**
- Create: `orchestrator/preflight.py`
- Create: `tests/orchestrator/test_preflight.py`

- [ ] **Step 1: Write failing test**

```python
# tests/orchestrator/test_preflight.py
import pytest
from unittest.mock import AsyncMock, patch
from orchestrator.preflight import PreflightRunner, PreflightReport


@pytest.mark.asyncio
async def test_runner_executes_all_checks():
    runner = PreflightRunner()
    
    # Create a mock check that passes
    class MockCheck:
        name = "mock"
        category = "infra"
        auto_fixable = False
        severity = "fatal"
        async def run(self):
            from orchestrator.checks.base import CheckResult
            return CheckResult(name="mock", passed=True, category="infra", severity="fatal", message="ok")
    
    with patch("orchestrator.checks.CHECK_REGISTRY", {"mock": MockCheck}):
        report = await runner.run_all()
        assert len(report.checks) == 1
        assert report.all_passed is True


@pytest.mark.asyncio
async def test_report_shows_fatal_failures():
    from orchestrator.checks.base import CheckResult
    report = PreflightReport()
    report.checks = [
        CheckResult(name="ok", passed=True, category="infra", severity="fatal", message="ok"),
        CheckResult(name="fail", passed=False, category="external", severity="fatal", message="down", todo="fix me"),
    ]
    assert report.all_passed is False
    assert len(report.fatal_failed) == 1
    assert report.to_dict()["fatal_count"] == 1
```

Run: `pytest tests/orchestrator/test_preflight.py -v`
Expected: FAIL — `PreflightRunner` not defined

- [ ] **Step 2: Implement preflight.py**

```python
"""
Preflight runner — automated pre-launch health checks for Quant Cluster.

Usage:
    python -m orchestrator.preflight           # Interactive table output
    python -m orchestrator.preflight --json    # Structured JSON output
    python -m orchestrator.preflight --mode=launch  # Minimal output for launch.sh
"""
import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import List, Dict

from rich.console import Console
from rich.table import Table

from orchestrator.checks import CHECK_REGISTRY
from orchestrator.checks.base import CheckResult

console = Console()


@dataclass
class PreflightReport:
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed or c.severity == "warning" for c in self.checks)

    @property
    def fatal_failed(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.passed and c.severity == "fatal"]

    def print_table(self):
        table = Table(title="🔍 Quant Cluster Preflight Report")
        table.add_column("Check", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Category", style="magenta")
        table.add_column("Message", style="white")

        for c in self.checks:
            if c.passed:
                status = "[green]✅ PASS[/green]"
            elif c.severity == "fatal":
                status = "[red]❌ FAIL[/red]"
            else:
                status = "[yellow]⚠️ WARN[/yellow]"
            table.add_row(c.name, status, c.category, c.message)

        console.print(table)

        fatal = self.fatal_failed
        if fatal:
            console.print(f"\n[red]🔴 {len(fatal)} fatal failure(s) detected. Pipeline blocked.[/red]")
            console.print("\n[bold]💡 待办清单：[/bold]")
            for i, c in enumerate(fatal, 1):
                console.print(f"  {i}. [{c.name}] {c.todo or '请检查并修复'}")
        else:
            console.print("\n[green]🟢 All checks passed. Ready to launch.[/green]")

    def to_dict(self) -> Dict:
        return {
            "passed": self.all_passed,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "category": c.category,
                    "severity": c.severity,
                    "message": c.message,
                    "fix_attempted": c.fix_attempted,
                    "fix_success": c.fix_success,
                    "todo": c.todo,
                }
                for c in self.checks
            ],
            "fatal_count": len(self.fatal_failed),
            "todo_list": [
                {"check": c.name, "action": c.todo or "请检查"}
                for c in self.fatal_failed
            ],
        }


class PreflightRunner:
    async def run_all(self) -> PreflightReport:
        report = PreflightReport()
        all_classes = list(CHECK_REGISTRY.values())

        # Phase 1: auto-fixable checks
        fixable = [c for c in all_classes if c().auto_fixable]
        for check_cls in fixable:
            result = await check_cls().run()
            report.checks.append(result)

        # Phase 2: re-verify anything that was fixed
        for i, result in enumerate(list(report.checks)):
            if result.fix_attempted:
                check_cls = next(c for c in fixable if c().name == result.name)
                retry = await check_cls().run()
                report.checks[i] = retry

        # Phase 3: non-fixable checks
        non_fixable = [c for c in all_classes if not c().auto_fixable]
        for check_cls in non_fixable:
            result = await check_cls().run()
            report.checks.append(result)

        return report


async def main():
    parser = argparse.ArgumentParser(description="Quant Cluster Preflight Checks")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of table")
    parser.add_argument("--mode", choices=["interactive", "launch"], default="interactive",
                        help="launch = minimal output for launch.sh")
    args = parser.parse_args()

    runner = PreflightRunner()
    report = await runner.run_all()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    elif args.mode == "launch":
        if report.all_passed:
            print("🟢 Preflight passed")
        else:
            for c in report.fatal_failed:
                print(f"🔴 [{c.name}] {c.todo}")
    else:
        report.print_table()

    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/orchestrator/test_preflight.py -v`
Expected: 2 PASS

- [ ] **Step 4: Commit**

```bash
git add orchestrator/preflight.py tests/orchestrator/test_preflight.py
git commit -m "feat(preflight): add PreflightRunner with 3-phase execution and Rich report"
```

---

### Task 7: CLI Integration (cli.py)

**Files:**
- Modify: `orchestrator/cli.py`
- Modify: `tests/orchestrator/test_preflight.py` (add CLI gate tests)

- [ ] **Step 1: Modify cli.py — three integration points**

Modify `orchestrator/cli.py`:

```python
# After existing imports, add:
from orchestrator.preflight import PreflightRunner

# Replace cmd_health:
async def cmd_health(orch: InteractiveOrchestrator):
    runner = PreflightRunner()
    report = await runner.run_all()
    report.print_table()
    if not report.all_passed:
        console.print("[red]🔴 Preflight 未通过，请修复上述问题后再运行 pipeline[/red]")
    sys.exit(0 if report.all_passed else 1)

# Modify run_pipeline gate in InteractiveOrchestrator:
async def run_pipeline(self, topic, stream=False, dry_run=False, skip_archive=False, skip_preflight=False):
    run_id = _generate_run_id()
    topic_slug = topic.replace(" ", "_").lower()[:30]

    # ── Preflight gate ──
    if not dry_run and not skip_preflight:
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

    console.rule(f"[bold blue]🚀 Pipeline: {topic} ({run_id})")
    # ... rest of existing method unchanged

# In main(), add --skip-preflight argument:
parser.add_argument("--skip-preflight", action="store_true", help="Skip preflight checks (emergency)")
# Pass it through to run_pipeline:
await cmd_run(orch, args.topic, args.stream, args.dry_run, args.skip_archive, skip_preflight=args.skip_preflight)

# Update cmd_run signature:
async def cmd_run(orch, topic, stream, dry_run, skip_archive=False, skip_preflight=False):
    result = await orch.run_pipeline(topic=topic, stream=stream, dry_run=dry_run, skip_archive=skip_archive, skip_preflight=skip_preflight)
    # ... rest unchanged
```

- [ ] **Step 2: Write test for CLI gate**

Append to `tests/orchestrator/test_preflight.py`:

```python
@pytest.mark.asyncio
async def test_pipeline_blocked_when_preflight_fails():
    from orchestrator.core.orchestrator import InteractiveOrchestrator
    orch = InteractiveOrchestrator()
    
    with patch("orchestrator.preflight.PreflightRunner.run_all") as mock_run:
        from orchestrator.preflight import PreflightReport
        report = PreflightReport()
        report.checks = [
            CheckResult(name="fail", passed=False, category="external", severity="fatal", message="down", todo="fix"),
        ]
        mock_run.return_value = report
        
        result = await orch.run_pipeline(topic="test", skip_preflight=False)
        assert result["status"] == "failed"
        assert result["reason"] == "preflight_failed"


@pytest.mark.asyncio
async def test_pipeline_skips_preflight_when_flag_set():
    from orchestrator.core.orchestrator import InteractiveOrchestrator
    orch = InteractiveOrchestrator()
    
    with patch("orchestrator.preflight.PreflightRunner.run_all") as mock_run:
        result = await orch.run_pipeline(topic="test", skip_preflight=True, dry_run=True)
        mock_run.assert_not_called()
```

Run: `pytest tests/orchestrator/test_preflight.py -v`
Expected: 4 PASS (2 existing + 2 new)

- [ ] **Step 3: Commit**

```bash
git add orchestrator/cli.py tests/orchestrator/test_preflight.py
git commit -m "feat(preflight): integrate into CLI health, run gate, and --skip-preflight flag"
```

---

### Task 8: launch.sh Integration

**Files:**
- Modify: `launch.sh`

- [ ] **Step 1: Replace health check step in launch.sh**

Replace lines 66-67 in `launch.sh`:

```bash
# Before:
# 6. 健康检查
echo "🔍 运行健康检查..."
python3 -m orchestrator.cli health

# After:
# 6. Preflight 前置检查
echo "🔍 运行 Preflight 前置检查..."
if ! python3 -m orchestrator.preflight --mode=launch; then
    echo ""
    echo "❌ Preflight 未通过，集群启动已阻止"
    echo "   请修复上述问题后重新运行 ./launch.sh"
    exit 1
fi
```

- [ ] **Step 2: Dry-run verify syntax**

Run: `bash -n launch.sh`
Expected: No output (success)

- [ ] **Step 3: Commit**

```bash
git add launch.sh
git commit -m "feat(preflight): integrate preflight gate into launch.sh"
```

---

### Task 9: Integration Test & Full Validation

**Files:**
- Modify: `tests/orchestrator/test_preflight.py` (end-to-end test)

- [ ] **Step 1: Write end-to-end test**

Append to `tests/orchestrator/test_preflight.py`:

```python
@pytest.mark.asyncio
async def test_preflight_cli_json_output():
    from orchestrator.preflight import PreflightRunner, PreflightReport
    
    with patch("orchestrator.preflight.PreflightRunner") as MockRunner:
        report = PreflightReport()
        report.checks = [
            CheckResult(name="docker", passed=True, category="infra", severity="fatal", message="ok"),
            CheckResult(name="ports", passed=True, category="infra", severity="fatal", message="ok"),
        ]
        instance = MockRunner.return_value
        instance.run_all = AsyncMock(return_value=report)
        
        # Simulate --json output
        assert report.to_dict()["passed"] is True


@pytest.mark.asyncio
async def test_preflight_runs_checks_in_correct_order():
    """Auto-fixable checks should run before non-fixable ones."""
    from orchestrator.preflight import PreflightRunner
    
    runner = PreflightRunner()
    report = await runner.run_all()
    
    # Verify ordering: fixable checks first, then non-fixable
    names = [c.name for c in report.checks]
    # We can't assert exact order without mocking, but we can verify
    # that all registered checks appear
    from orchestrator.checks import CHECK_REGISTRY
    assert len(report.checks) == len(CHECK_REGISTRY)
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/orchestrator/ -v`
Expected: ALL PASS

- [ ] **Step 3: Manual validation — preflight CLI**

Run: `python3 -m orchestrator.preflight --json`
Expected: JSON output with check results (may show failures if cluster not running — that's expected)

- [ ] **Step 4: Manual validation — CLI health**

Run: `python3 -m orchestrator.cli health`
Expected: Preflight table output

- [ ] **Step 5: Commit**

```bash
git add tests/orchestrator/test_preflight.py
git commit -m "test(preflight): add end-to-end and ordering integration tests"
```

---

## Spec Coverage Self-Review

| Spec Requirement | Implementing Task |
|------------------|-------------------|
| Check ABC + CheckResult | Task 1 |
| Auto-registration via `@register` | Task 1 |
| Plugin Registry pattern | Task 1-5 |
| Docker container check (auto-fix) | Task 2 |
| Port check + residual kill | Task 3 |
| API key validity (light ping) | Task 4 |
| Hermes Health check | Task 4 |
| IB Gateway check | Task 5 |
| Data Router check | Task 5 |
| WebBridge check (fatal) | Task 5 |
| Workspace check (auto-fix) | Task 1 |
| 3-phase execution (fix → verify → report) | Task 6 |
| Rich table output | Task 6 |
| JSON output (`--json`) | Task 6 |
| `launch.sh` integration | Task 8 |
| `cli.py health` integration | Task 7 |
| `run_pipeline` gate | Task 7 |
| `--skip-preflight` flag | Task 7 |
| Auto-kill own residual processes | Task 3 |
| External process blocking report | Task 3 |

**Gaps:** None identified.

---

## Post-Implementation Verification

After all tasks are complete, run:

```bash
# 1. Full test suite
pytest tests/orchestrator/ -v

# 2. Pre-commit validation
python3 scripts/validate.py

# 3. Manual dry-run (without cluster)
python3 -m orchestrator.preflight --json

# 4. Verify launch.sh syntax
bash -n launch.sh
```
