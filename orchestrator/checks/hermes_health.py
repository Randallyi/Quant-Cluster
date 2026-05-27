"""Hermes agent health check via HTTP /health endpoints."""
import asyncio

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
    TIMEOUT = aiohttp.ClientTimeout(total=5)

    async def run(self) -> CheckResult:
        failed: list[str] = []
        total = len(self.EXPECTED_AGENTS)

        async with aiohttp.ClientSession(timeout=self.TIMEOUT) as session:
            for agent, port in self.EXPECTED_AGENTS.items():
                url = f"http://localhost:{port}/health"
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            failed.append(agent)
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    failed.append(agent)

        if not failed:
            return CheckResult(
                name=self.name,
                passed=True,
                category=self.category,
                severity=self.severity,
                message=f"{total}/{total} agents responding.",
            )

        return CheckResult(
            name=self.name,
            passed=False,
            category=self.category,
            severity=self.severity,
            message=f"Failed agents: {', '.join(failed)}.",
            todo=f"Please check Docker container status: {', '.join(failed)}",
        )
