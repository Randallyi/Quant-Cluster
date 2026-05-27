"""WebBridge health check."""
import asyncio

import aiohttp

from orchestrator.checks.base import Check, CheckResult
from orchestrator.checks import register


@register
class WebBridgeCheck(Check):
    name = "webbridge"
    category = "external"
    auto_fixable = False
    severity = "fatal"
    TIMEOUT = aiohttp.ClientTimeout(total=5)

    async def run(self) -> CheckResult:
        try:
            async with aiohttp.ClientSession(timeout=self.TIMEOUT) as session:
                async with session.get("http://localhost:10086/health") as resp:
                    if resp.status == 200:
                        return CheckResult(
                            name=self.name,
                            passed=True,
                            category=self.category,
                            severity=self.severity,
                            message="WebBridge responding.",
                        )
                    else:
                        return CheckResult(
                            name=self.name,
                            passed=False,
                            category=self.category,
                            severity=self.severity,
                            message=f"WebBridge returned HTTP {resp.status}.",
                            todo="Please start WebBridge: python3 -m webbridge.server",
                        )
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return CheckResult(
                name=self.name,
                passed=False,
                category=self.category,
                severity=self.severity,
                message="WebBridge unreachable.",
                todo="Please start WebBridge: python3 -m webbridge.server",
            )
