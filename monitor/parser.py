"""Regex-based parser for Hermes agent.log lines."""

import re
from typing import Optional

# Timestamp prefix shared by all patterns
_TIMESTAMP_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})"
)

_API_CALL_RE = re.compile(
    r"API call #(?P<call_num>\d+):\s*"
    r"model=(?P<model>\S+)\s+"
    r"provider=(?P<provider>\S+)\s+"
    r"in=(?P<input_tokens>\d+)\s+"
    r"out=(?P<output_tokens>\d+)\s+"
    r"total=(?P<total_tokens>\d+)\s+"
    r"latency=(?P<latency_sec>[\d.]+)s"
)

_TOOL_CALL_RE = re.compile(
    r"tool (?P<tool>\S+) completed\s*"
    r"\((?P<duration_sec>[\d.]+)s,\s*"
    r"(?P<output_chars>\d+) chars\)"
)

_TURN_END_RE = re.compile(
    r"Turn ended:\s*"
    r"reason=(?P<reason>.+?)\s+"
    r"model=\S+\s+"
    r"api_calls=(?P<api_calls>\S+)\s+"
    r"budget=(?P<budget>\S+)\s+"
    r"tool_turns=(?P<tool_turns>\d+)"
)

_TURN_START_RE = re.compile(
    r"conversation turn:\s*"
    r"session=(?P<session>\S+)\s+"
    r"model=(?P<model>\S+)\s+"
    r"provider=\S+\s+"
    r"platform=\S+\s+"
    r"history=(?P<history_len>\d+)"
)


def _extract_timestamp(line: str) -> tuple[Optional[str], str]:
    """Return (timestamp, remainder) if a timestamp is found, else (None, line)."""
    m = _TIMESTAMP_RE.match(line)
    if m:
        return m.group("timestamp"), line[m.end():]
    return None, line


def parse_log_line(line: str) -> dict:
    """Parse a single Hermes agent.log line into a structured dict."""
    timestamp, remainder = _extract_timestamp(line)
    result: dict = {}
    if timestamp is not None:
        result["timestamp"] = timestamp

    m = _API_CALL_RE.search(remainder)
    if m:
        result.update(
            {
                "activity": "api_call",
                "call_num": int(m.group("call_num")),
                "model": m.group("model"),
                "provider": m.group("provider"),
                "input_tokens": int(m.group("input_tokens")),
                "output_tokens": int(m.group("output_tokens")),
                "total_tokens": int(m.group("total_tokens")),
                "latency_sec": float(m.group("latency_sec")),
            }
        )
        return result

    m = _TOOL_CALL_RE.search(remainder)
    if m:
        result.update(
            {
                "activity": "tool_call",
                "tool": m.group("tool"),
                "duration_sec": float(m.group("duration_sec")),
                "output_chars": int(m.group("output_chars")),
            }
        )
        return result

    m = _TURN_END_RE.search(remainder)
    if m:
        result.update(
            {
                "activity": "turn_end",
                "reason": m.group("reason"),
                "api_calls": m.group("api_calls"),
                "budget": m.group("budget"),
                "tool_turns": int(m.group("tool_turns")),
            }
        )
        return result

    m = _TURN_START_RE.search(remainder)
    if m:
        result.update(
            {
                "activity": "turn_start",
                "session": m.group("session"),
                "model": m.group("model"),
                "history_len": int(m.group("history_len")),
            }
        )
        return result

    # Fallback
    result["activity"] = "log"
    result["raw"] = line.strip()
    return result
