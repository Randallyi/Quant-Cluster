"""Docker container health check with auto-restart."""
import asyncio
from typing import List, Set

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

    async def _get_running_containers(self) -> Set[str]:
        """Return set of currently running container names."""
        proc = await asyncio.create_subprocess_exec(
            "docker", "ps", "--format", "{{.Names}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        names = stdout.decode().strip().splitlines()
        return set(names)

    async def _start_missing(self, missing: List[str]) -> bool:
        """Attempt to start missing containers via docker compose."""
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "up", "-d", *missing,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0

    async def run(self) -> CheckResult:
        running = await self._get_running_containers()
        missing = [c for c in self.EXPECTED if c not in running]

        if not missing:
            return CheckResult(
                name=self.name,
                passed=True,
                category=self.category,
                severity=self.severity,
                message="All expected Docker containers are running.",
            )

        # Attempt auto-fix: start missing containers
        fix_attempted = True
        fix_success = await self._start_missing(missing)

        if fix_success:
            running = await self._get_running_containers()
            still_missing = [c for c in self.EXPECTED if c not in running]
            if not still_missing:
                return CheckResult(
                    name=self.name,
                    passed=True,
                    category=self.category,
                    severity=self.severity,
                    message=f"Restarted missing containers: {', '.join(missing)}.",
                    fix_attempted=fix_attempted,
                    fix_success=True,
                )

        still_missing = [c for c in missing if c not in running]
        return CheckResult(
            name=self.name,
            passed=False,
            category=self.category,
            severity=self.severity,
            message=f"Missing containers: {', '.join(still_missing)}.",
            fix_attempted=fix_attempted,
            fix_success=False,
            todo=f"docker compose up -d failed, please manually check: {', '.join(still_missing)}",
        )
