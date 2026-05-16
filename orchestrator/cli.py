"""
Quant Cluster Orchestrator — async CLI entrypoint
Coordinates 5 Hermes Docker agents through the quant strategy pipeline.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add parent directory to path so orchestrator package imports work
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel

from orchestrator.core.orchestrator import InteractiveOrchestrator
from orchestrator.core.dag import WORKSPACE_ROOT

console = Console()


async def cmd_health(orch: InteractiveOrchestrator):
    ok = await orch.health_check_all()
    sys.exit(0 if ok else 1)


async def cmd_run(orch: InteractiveOrchestrator, topic: str, stream: bool, dry_run: bool, skip_archive: bool = False):
    result = await orch.run_pipeline(topic=topic, stream=stream, dry_run=dry_run, skip_archive=skip_archive)
    console.print_json(json.dumps(result))
    sys.exit(0 if result.get("status") == "success" else 1)


async def cmd_status(orch: InteractiveOrchestrator):
    orch.status_board()


async def cmd_clear():
    from orchestrator.core.dag import AGENTS
    for info in AGENTS.values():
        ws = WORKSPACE_ROOT / info["workspace"]
        ws.mkdir(parents=True, exist_ok=True)
        for f in ws.iterdir():
            if f.is_file():
                f.unlink()
    console.print("[green]Workspace cleared[/green]")


async def main():
    parser = argparse.ArgumentParser(description="Quant Cluster Orchestrator")
    parser.add_argument("command", choices=["health", "run", "status", "clear"])
    parser.add_argument("--topic", default="QQQ Momentum vs Reversion Strategy", help="Research topic")
    parser.add_argument("--stream", action="store_true", help="Enable streaming output")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually call agents")
    parser.add_argument("--from-stage", default=None, help="Start from this stage (skip earlier stages)")
    parser.add_argument("--skip-archive", action="store_true", help="Skip archive + cleanup after pipeline completion")
    args = parser.parse_args()

    if args.command == "clear":
        await cmd_clear()
        return

    orch = InteractiveOrchestrator()

    if args.command == "health":
        await cmd_health(orch)
    elif args.command == "run":
        if args.from_stage:
            # Skip stages before from_stage
            from orchestrator.core.dag import EXECUTION_ORDER
            if args.from_stage not in EXECUTION_ORDER:
                console.print(f"[red]Unknown stage: {args.from_stage}[/red]")
                sys.exit(1)
            orch._skip_stages = set(EXECUTION_ORDER[:EXECUTION_ORDER.index(args.from_stage)])
            console.print(f"[dim]Skipping stages: {orch._skip_stages}[/dim]")
        await cmd_run(orch, args.topic, args.stream, args.dry_run, args.skip_archive)
    elif args.command == "status":
        await cmd_status(orch)


if __name__ == "__main__":
    asyncio.run(main())
