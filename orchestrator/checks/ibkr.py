"""IBKR gateway and Data Router health checks."""
import asyncio
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
            sock = socket.create_connection(("localhost", 7497), timeout=5)
            sock.close()
        except OSError:
            return CheckResult(
                name=self.name,
                passed=False,
                category=self.category,
                severity=self.severity,
                message="TWS port 7497 unreachable.",
                todo="Please start IB Gateway and configure Trusted IP: 192.168.65.0/24",
            )

        return CheckResult(
            name=self.name,
            passed=True,
            category=self.category,
            severity=self.severity,
            message="TWS port 7497 reachable.",
        )


@register
class DataRouterCheck(Check):
    name = "data_router"
    category = "external"
    auto_fixable = False
    severity = "fatal"
    TIMEOUT = aiohttp.ClientTimeout(total=5)

    async def run(self) -> CheckResult:
        try:
            async with aiohttp.ClientSession(timeout=self.TIMEOUT) as session:
                async with session.get("http://localhost:8888/health") as resp:
                    if resp.status == 200:
                        return CheckResult(
                            name=self.name,
                            passed=True,
                            category=self.category,
                            severity=self.severity,
                            message="Data Router healthy.",
                        )
                    else:
                        return CheckResult(
                            name=self.name,
                            passed=False,
                            category=self.category,
                            severity=self.severity,
                            message=f"Data Router returned HTTP {resp.status}.",
                            todo="Please check docker logs quant-data-router",
                        )
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return CheckResult(
                name=self.name,
                passed=False,
                category=self.category,
                severity=self.severity,
                message="Data Router unreachable.",
                todo="Please check docker logs quant-data-router",
            )
