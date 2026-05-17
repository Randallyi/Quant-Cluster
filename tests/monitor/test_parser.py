"""Unit tests for monitor.parser."""

import pytest
from monitor.parser import parse_log_line


@pytest.mark.parametrize(
    "line,expected",
    [
        (
            "2026-05-17 09:02:56,504 INFO [api-8641fe00c0ebb1d2] run_agent: API call #16: model=claude-sonnet-4-6 provider=anthropic in=78692 out=3834 total=82526 latency=124.0s cache=74496/78692 (95%)",
            {
                "activity": "api_call",
                "timestamp": "2026-05-17 09:02:56,504",
                "call_num": 16,
                "model": "claude-sonnet-4-6",
                "provider": "anthropic",
                "input_tokens": 78692,
                "output_tokens": 3834,
                "total_tokens": 82526,
                "latency_sec": 124.0,
            },
        ),
        (
            "2026-05-17 09:02:57,162 INFO [api-8641fe00c0ebb1d2] run_agent: tool write_file completed (0.65s, 115 chars)",
            {
                "activity": "tool_call",
                "timestamp": "2026-05-17 09:02:57,162",
                "tool": "write_file",
                "duration_sec": 0.65,
                "output_chars": 115,
            },
        ),
        (
            "2026-05-17 09:06:05,807 INFO [api-8641fe00c0ebb1d2] run_agent: Turn ended: reason=text_response(finish_reason=stop) model=claude-sonnet-4-6 api_calls=20/90 budget=20/90 tool_turns=12 last_msg_role=assistant response_len=1170 session=20260517_085822_907f10",
            {
                "activity": "turn_end",
                "timestamp": "2026-05-17 09:06:05,807",
                "reason": "text_response(finish_reason=stop)",
                "api_calls": "20/90",
                "budget": "20/90",
                "tool_turns": 12,
            },
        ),
        (
            "2026-05-17 09:06:07,216 INFO [20260517_090605_226322] run_agent: conversation turn: session=20260517_090605_226322 model=claude-sonnet-4-6 provider=anthropic platform=api_server history=32 msg='Review the conversation above...'",
            {
                "activity": "turn_start",
                "timestamp": "2026-05-17 09:06:07,216",
                "session": "20260517_090605_226322",
                "model": "claude-sonnet-4-6",
                "history_len": 32,
            },
        ),
        (
            "some completely unparseable garbage line",
            {
                "activity": "log",
                "raw": "some completely unparseable garbage line",
            },
        ),
    ],
)
def test_parse_log_line(line: str, expected: dict) -> None:
    """parse_log_line must extract the correct structured fields."""
    result = parse_log_line(line)
    assert result == expected
