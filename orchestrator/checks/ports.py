"""Port availability check with auto-kill for residual processes."""
import asyncio
import os
from typing import Dict, List, Optional

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

    async def _get_listener_pid(self, port: int) -> Optional[int]:
        """Return PID listening on port, or None if free."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "lsof", "-Pi", f":{port}", "-sTCP:LISTEN", "-t",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, PermissionError):
            return None
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        try:
            return int(stdout.decode().strip().splitlines()[0])
        except (ValueError, IndexError):
            return None

    async def _get_process_info(self, pid: int) -> Dict[str, str]:
        """Return dict with process name (comm) and args for PID."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ps", "-p", str(pid), "-o", "comm=,args=",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, PermissionError):
            return {"comm": "", "args": ""}
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return {"comm": "", "args": ""}
        line = stdout.decode().strip()
        parts = line.split(None, 1)
        return {
            "comm": parts[0] if parts else "",
            "args": parts[1] if len(parts) > 1 else "",
        }

    async def _is_docker_process(self, pid: int) -> bool:
        """Check if process belongs to Docker."""
        info = await self._get_process_info(pid)
        comm = info.get("comm", "").lower()
        return "docker" in comm or "com.docker" in comm

    async def _is_our_residual(self, pid: int) -> bool:
        """Check if process is one of our residual processes."""
        info = await self._get_process_info(pid)
        text = f"{info.get('comm', '')} {info.get('args', '')}".lower()
        return any(pattern in text for pattern in self.OUR_PATTERNS)

    async def run(self) -> CheckResult:
        blocked: List[str] = []
        fix_attempted = False
        fix_success = True

        for port in self.EXPECTED_PORTS:
            pid = await self._get_listener_pid(port)
            if pid is None:
                continue

            if await self._is_docker_process(pid):
                continue

            if await self._is_our_residual(pid):
                fix_attempted = True
                try:
                    os.kill(pid, 9)
                except (OSError, ProcessLookupError):
                    fix_success = False
                    blocked.append(f"{port} (PID {pid} — kill failed)")
                    continue

                await asyncio.sleep(2)
                pid_after = await self._get_listener_pid(port)
                if pid_after is not None:
                    fix_success = False
                    blocked.append(f"{port} (PID {pid} — still occupied after kill)")
                continue

            # External process — do NOT kill
            info = await self._get_process_info(pid)
            blocked.append(f"{port} (PID {pid} — {info['comm']})")

        if blocked:
            return CheckResult(
                name=self.name,
                passed=False,
                category=self.category,
                severity=self.severity,
                message=f"Blocked ports: {', '.join(blocked)}.",
                fix_attempted=fix_attempted,
                fix_success=fix_success if fix_attempted else False,
                todo=f"Free blocked ports: {', '.join(str(b.split()[0]) for b in blocked)}",
            )

        return CheckResult(
            name=self.name,
            passed=True,
            category=self.category,
            severity=self.severity,
            message="All expected ports are available.",
            fix_attempted=fix_attempted,
            fix_success=fix_success if fix_attempted else True,
        )
