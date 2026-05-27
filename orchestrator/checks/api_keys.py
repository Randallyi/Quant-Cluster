"""API key availability and validity check."""
import asyncio
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
    TIMEOUT = aiohttp.ClientTimeout(total=10)

    async def run(self) -> CheckResult:
        missing = [k for k in self.REQUIRED_KEYS if not os.environ.get(k)]

        if missing:
            return CheckResult(
                name=self.name,
                passed=False,
                category=self.category,
                severity=self.severity,
                message=f"Missing API keys: {', '.join(missing)}.",
                todo=f"Please configure in .env: {', '.join(missing)}",
            )

        # Light-ping Kimi API to verify ANTHROPIC_API_KEY validity
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        try:
            async with aiohttp.ClientSession(timeout=self.TIMEOUT) as session:
                async with session.get(
                    self.KIMI_MODELS_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                ) as resp:
                    if resp.status != 200:
                        return CheckResult(
                            name=self.name,
                            passed=False,
                            category=self.category,
                            severity=self.severity,
                            message=f"Kimi API ping failed with status {resp.status}.",
                            todo="Please check network connectivity and API key validity.",
                        )
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            return CheckResult(
                name=self.name,
                passed=False,
                category=self.category,
                severity=self.severity,
                message=f"Kimi API ping error: {exc}.",
                todo="Please check network connectivity and API key validity.",
            )

        return CheckResult(
            name=self.name,
            passed=True,
            category=self.category,
            severity=self.severity,
            message="All API keys are valid.",
        )
