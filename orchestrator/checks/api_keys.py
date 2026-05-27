"""API key availability and validity check."""
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
                todo=f"请在 .env 中配置: {', '.join(missing)}",
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
                            todo="请检查网络连接和 API key 有效性",
                        )
        except aiohttp.ClientError as exc:
            return CheckResult(
                name=self.name,
                passed=False,
                category=self.category,
                severity=self.severity,
                message=f"Kimi API ping error: {exc}.",
                todo="请检查网络连接和 API key 有效性",
            )

        return CheckResult(
            name=self.name,
            passed=True,
            category=self.category,
            severity=self.severity,
            message="所有 key 有效",
        )
