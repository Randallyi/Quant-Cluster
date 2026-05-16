"""InteractiveOrchestrator — async pipeline engine with consultation support."""
import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel

from orchestrator.core.dag import AGENTS, DAG, EXECUTION_ORDER, AGENT_CONFIG_ROOT, WORKSPACE_ROOT
from orchestrator.core.state_db import StateDB
from orchestrator.clients.hermes import AsyncHermesClient
from orchestrator.clients.data_router import DataRouterClient

console = Console()

ARCHIVE_ROOT = WORKSPACE_ROOT / "archive"

# ── Archive rules ──────────────────────────────────────────────────
# Files matching KEEP_PATTERNS are copied into archive/{run_id}/
# Files matching CLEAN_PATTERNS are deleted from workspace after archiving
_KEEP_PATTERNS = [
    "*.md",          # all reports (bilingual)
    "*.png",         # all visualizations
    "*.html",        # final HTML report
    "*metadata*.json",
    "references.json",
    "data_requirements.json",
    "audit_summary.json",
    "audit_computed.json",
    "*provenance*.json",
    "out_of_sample_sharpe.json",
]
_CLEAN_PATTERNS = [
    "*.parquet",
    "*.csv",
    "raw",
    "raw_data",
    "*.py",
    ".agent_checkpoint.json",
    "fetch_summary.json",
    ".run_id",
]


def _generate_run_id() -> str:
    return f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _check_upstream_ready(agent_name: str) -> bool:
    """Check whether all upstream artifacts exist."""
    deps = DAG[agent_name]["deps"]
    for dep in deps:
        dep_ws = WORKSPACE_ROOT / AGENTS[dep]["workspace"]
        expected = DAG[dep]["output_files"]
        if not any(dep_ws.glob(pattern) for pattern in expected):
            return False
    return True


def _clear_workspace_for_run(topic_slug: str):
    """Clean workspace for a new run (keep structure, remove old files)."""
    for info in AGENTS.values():
        ws = WORKSPACE_ROOT / info["workspace"]
        ws.mkdir(parents=True, exist_ok=True)
        for f in ws.iterdir():
            if f.is_file():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f)
        (ws / ".run_id").write_text(topic_slug)


def _should_archive(path: Path) -> bool:
    """Return True if file should be archived."""
    # Skip hidden files (except .run_id is handled separately)
    if path.name.startswith(".") and path.name != ".run_id":
        return False
    # Skip large JSON files (>100KB)
    if path.suffix == ".json" and path.stat().st_size > 100_000:
        return False
    # Skip raw data JSONs
    if path.name.startswith("raw_") and path.suffix == ".json":
        return False
    # Skip raw/ and raw_data/ directories
    if path.is_dir() and path.name in ("raw", "raw_data"):
        return False
    # Keep by pattern
    for pattern in _KEEP_PATTERNS:
        if path.match(pattern):
            return True
    return False


def _should_clean(path: Path) -> bool:
    """Return True if file/dir should be cleaned from workspace after archive."""
    for pattern in _CLEAN_PATTERNS:
        if path.match(pattern):
            return True
        if path.is_dir() and path.name == pattern:
            return True
    # Also clean large JSON files
    if path.suffix == ".json" and path.stat().st_size > 100_000:
        return True
    if path.name.startswith("raw_") and path.suffix == ".json":
        return True
    return False


def _archive_and_cleanup_run(run_id: str, topic: str) -> Dict:
    """Archive valuable artifacts and clean intermediate data.

    SAFETY: Only cleans workspace if archive succeeded AND archive is non-empty.
    """
    archive_dir = ARCHIVE_ROOT / run_id
    archive_dir.mkdir(parents=True, exist_ok=True)

    archived_files = []
    total_archived_bytes = 0

    # ── Phase 1: Archive ────────────────────────────────────────────
    for agent_name, info in AGENTS.items():
        ws = WORKSPACE_ROOT / info["workspace"]
        if not ws.exists():
            continue

        ws_archive = archive_dir / info["workspace"]
        ws_archive.mkdir(parents=True, exist_ok=True)

        for item in ws.rglob("*"):
            if item.is_file() and _should_archive(item):
                rel = item.relative_to(ws)
                dst = ws_archive / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst)
                archived_files.append(str(rel))
                total_archived_bytes += item.stat().st_size

    # ── Phase 2: Safety checks ─────────────────────────────────────
    # Check: Verify archive files exist on disk (only if we expected to archive)
    if archived_files:
        archive_file_count = sum(1 for _ in archive_dir.rglob("*") if _.is_file() and _.name != "archive_manifest.json")
        if archive_file_count == 0:
            console.log("[yellow]⚠️  Archive verification failed — skipping workspace cleanup[/yellow]")
            manifest = {
                "run_id": run_id,
                "topic": topic,
                "archived_at": datetime.now().isoformat(),
                "archived_files_count": 0,
                "archived_size_mb": 0.0,
                "cleaned_items_count": 0,
                "warning": "archive_verification_failed_skipped_cleanup",
            }
            (archive_dir / "archive_manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False)
            )
            return manifest

    # ── Phase 3: Cleanup (always execute — intermediate files must not leak) ────────
    cleaned_files = []
    for agent_name, info in AGENTS.items():
        ws = WORKSPACE_ROOT / info["workspace"]
        if not ws.exists():
            continue

        for item in list(ws.rglob("*")):
            if not item.exists():
                continue
            if _should_clean(item):
                if item.is_dir():
                    shutil.rmtree(item)
                    cleaned_files.append(f"[dir] {item.name}")
                elif item.is_file():
                    item.unlink()
                    cleaned_files.append(str(item.relative_to(ws)))

    # Write archive manifest
    manifest = {
        "run_id": run_id,
        "topic": topic,
        "archived_at": datetime.now().isoformat(),
        "archived_files_count": len(archived_files),
        "archived_size_mb": round(total_archived_bytes / (1024 * 1024), 2),
        "cleaned_items_count": len(cleaned_files),
    }
    (archive_dir / "archive_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False)
    )

    return manifest


def _read_soul(agent_name: str) -> str:
    path = AGENT_CONFIG_ROOT / agent_name / "SOUL.md"
    return path.read_text() if path.exists() else "You are a helpful assistant."


def _parse_consultation(text: str) -> Dict:
    """Best-effort extraction of consultation payload from agent text."""
    lines = text.splitlines()
    question = "Agent needs guidance"
    options: List[str] = []
    in_options = False
    for line in lines:
        stripped = line.strip()
        if "问题:" in stripped or "question:" in stripped.lower():
            question = stripped.split(":", 1)[-1].strip()
        elif "选项:" in stripped or "options:" in stripped.lower() or stripped.startswith("["):
            in_options = True
        if in_options and stripped:
            options.append(stripped)
    return {"question": question, "options": options[:5], "raw": text}


class InteractiveOrchestrator:
    def __init__(self, db_path: Optional[Path] = None):
        self.db = StateDB(db_path)
        self.clients = {
            name: AsyncHermesClient(info["port"], info["api_key"])
            for name, info in AGENTS.items()
        }
        self.data_router = DataRouterClient()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def health_check_all(self) -> bool:
        table = Table(title="Hermes Agent Health Check")
        table.add_column("Agent", style="cyan")
        table.add_column("Port", style="magenta")
        table.add_column("Status", style="green")

        results = await asyncio.gather(
            *[self.clients[name].health_check() for name in AGENTS],
            return_exceptions=True,
        )
        all_ok = True
        for name, ok in zip(AGENTS, results):
            healthy = ok is True
            status = "[green]✅ Online[/green]" if healthy else "[red]❌ Offline[/red]"
            table.add_row(name, str(AGENTS[name]["port"]), status)
            if not healthy:
                all_ok = False
        console.print(table)
        return all_ok

    async def run_pipeline(
        self,
        topic: str,
        stream: bool = False,
        dry_run: bool = False,
        skip_archive: bool = False,
    ) -> Dict:
        run_id = _generate_run_id()
        topic_slug = topic.replace(" ", "_").lower()[:30]

        console.rule(f"[bold blue]🚀 Pipeline: {topic} ({run_id})")
        self.db.create_run(run_id, topic)
        skip_stages = getattr(self, "_skip_stages", set())
        if not skip_stages:
            _clear_workspace_for_run(topic_slug)
        else:
            # Only clear workspaces for stages that will run
            for agent_name in EXECUTION_ORDER:
                if agent_name not in skip_stages:
                    ws = WORKSPACE_ROOT / AGENTS[agent_name]["workspace"]
                    ws.mkdir(parents=True, exist_ok=True)
                    for f in ws.iterdir():
                        if f.is_file():
                            f.unlink()
                    (ws / ".run_id").write_text(topic_slug)


        for agent_name in EXECUTION_ORDER:
            if agent_name in skip_stages:
                console.log(f"[dim]Skipping {agent_name} (already completed)[/dim]")
                continue
            result = await self._execute_agent(
                agent_name=agent_name,
                topic=topic,
                run_id=run_id,
                stream=stream,
                dry_run=dry_run,
            )
            if result["status"] != "success":
                self.db.update_run_status(run_id, result["status"])
                console.rule(f"[bold red]❌ Pipeline failed at {agent_name}")
                return {**result, "run_id": run_id}

        self.db.update_run_status(run_id, "completed")
        console.rule(f"[bold green]✅ Pipeline completed: {run_id}")

        # ── Archive + cleanup (skip on dry-run or --skip-archive) ────
        if not dry_run and not skip_archive:
            console.log(f"[dim]Archiving run {run_id} ...[/dim]")
            manifest = _archive_and_cleanup_run(run_id, topic)
            console.log(
                f"[dim]Archived {manifest['archived_files_count']} files "
                f"({manifest['archived_size_mb']} MB) → {ARCHIVE_ROOT / run_id}[/dim]"
            )
            console.log(
                f"[dim]Cleaned {manifest['cleaned_items_count']} intermediate items[/dim]"
            )

            # ── Generate HTML report ───────────────────────────────────
            try:
                from orchestrator.core.html_reporter import generate_html_report
                html_path = generate_html_report(run_id, topic, WORKSPACE_ROOT, ARCHIVE_ROOT)
                console.log(f"[green]📊 HTML report: {html_path}[/green]")
            except Exception as e:
                console.log(f"[yellow]HTML report generation skipped: {e}[/yellow]")
        elif skip_archive:
            console.log("[yellow]⏭️  Archive + cleanup skipped (--skip-archive)[/yellow]")

        return {"status": "success", "run_id": run_id}

    # ------------------------------------------------------------------
    # Agent execution
    # ------------------------------------------------------------------
    async def _execute_agent(
        self,
        agent_name: str,
        topic: str,
        run_id: str,
        stream: bool,
        dry_run: bool,
    ) -> Dict:
        console.rule(f"[bold cyan]▶️  Stage: {agent_name}")

        # 1. upstream check
        if not _check_upstream_ready(agent_name):
            console.log(f"[red]Upstream missing — {agent_name} cannot start[/red]")
            return {"status": "failed", "agent": agent_name, "reason": "upstream_missing"}

        task_id = self.db.create_task(run_id, agent_name)
        self.db.update_task_status(task_id, "running")

        if dry_run:
            console.log(f"[dim]Dry run: skipping {agent_name}[/dim]")
            self.db.update_task_status(task_id, "success", output_summary="Dry run")
            return {"status": "success", "agent": agent_name}

        system_prompt = _read_soul(agent_name)
        user_prompt = DAG[agent_name]["prompt_template"].format(topic=topic)

        console.log(f"[dim]Calling {agent_name} @ localhost:{AGENTS[agent_name]['port']} ...[/dim]")

        # 2. call agent
        if stream:
            result_text = await self._call_agent_stream(agent_name, system_prompt, user_prompt)
        else:
            result_text = await self.clients[agent_name].chat(system_prompt, user_prompt, timeout=600)

        # 3. check errors
        if result_text.startswith("[ERROR]"):
            console.log(f"[red]{agent_name} failed[/red]")
            self.db.update_task_status(task_id, "failed", error_log=result_text)
            return {"status": "failed", "agent": agent_name, "reason": "agent_error"}

        # 4. consultation handling
        if "[CONSULTATION_NEEDED]" in result_text:
            self.db.update_task_status(task_id, "consultation_needed", output_summary=result_text[:500])
            consultation = _parse_consultation(result_text)
            self.db.create_consultation(run_id, agent_name, consultation["question"], json.dumps(consultation["options"]))

            console.print(Panel.fit(
                f"[yellow bold]⚠️  CONSULTATION NEEDED[/yellow bold]\n"
                f"Agent: {agent_name}\n"
                f"Question: {consultation['question']}\n",
                title="Orchestrator Decision Required",
            ))

            resolution = await self._handle_consultation_interactive(agent_name, consultation)

            if resolution["action"] == "resume":
                console.log(f"[dim]Resuming {agent_name} with instructions...[/dim]")
                resume_prompt = f"{user_prompt}\n\n[ORCHESTRATOR_DECISION]\n{resolution['instruction']}"
                result_text = await self.clients[agent_name].chat(system_prompt, resume_prompt, timeout=600)
                if result_text.startswith("[ERROR]"):
                    self.db.update_task_status(task_id, "failed", error_log=result_text)
                    return {"status": "failed", "agent": agent_name, "reason": "agent_error"}
            elif resolution["action"] == "skip":
                self.db.update_task_status(task_id, "skipped", output_summary="Skipped by orchestrator")
                console.log(f"[yellow]{agent_name} skipped[/yellow]")
                return {"status": "success", "agent": agent_name, "skipped": True}
            elif resolution["action"] == "abort":
                self.db.update_task_status(task_id, "aborted")
                console.log(f"[red]{agent_name} aborted by user[/red]")
                return {"status": "failed", "agent": agent_name, "reason": "aborted_by_user"}

        console.log(f"[green]{agent_name} completed[/green]")
        self.db.update_task_status(task_id, "success", output_summary=result_text[:500])
        await asyncio.sleep(1)  # allow filesystem sync
        return {"status": "success", "agent": agent_name}

    async def _call_agent_stream(self, agent_name: str, system_prompt: str, user_prompt: str) -> str:
        """Stream agent response to console, collecting full text."""
        full = ""
        with Live(console=console, refresh_per_second=10) as live:
            async for chunk in self.clients[agent_name].chat_stream(system_prompt, user_prompt):
                full += chunk
                live.update(Panel(f"[dim]{full[-500:]}[/dim]", title=f"🔄 {agent_name}"))
        return full

    async def _handle_consultation_interactive(self, agent_name: str, consultation: Dict) -> Dict:
        """Prompt user for a decision via CLI."""
        options = consultation.get("options", [])
        for i, opt in enumerate(options, 1):
            console.print(f"  [{i}] {opt}")
        console.print("  [s] Skip this agent")
        console.print("  [a] Abort pipeline")

        while True:
            choice = console.input("Your choice [1-{} / s / a]: ".format(len(options) if options else 0)).strip().lower()
            if choice == "s":
                return {"action": "skip", "instruction": ""}
            if choice == "a":
                return {"action": "abort", "instruction": ""}
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(options):
                    return {"action": "resume", "instruction": options[idx]}
            except ValueError:
                pass
            console.print("[red]Invalid choice, try again.[/red]")

    # ------------------------------------------------------------------
    # Status board
    # ------------------------------------------------------------------
    def status_board(self):
        runs = self.db.list_runs()
        if not runs:
            console.print("[dim]No runs yet[/dim]")
            return
        table = Table(title="Pipeline History")
        table.add_column("Run ID", style="cyan")
        table.add_column("Topic", style="white")
        table.add_column("Status", style="green")
        table.add_column("Created", style="dim")
        for r in runs:
            sc = "green" if r["status"] == "completed" else "yellow" if r["status"] == "pending" else "red"
            table.add_row(r["run_id"], r["topic"], f"[{sc}]{r['status']}[/{sc}]", r["created_at"])
        console.print(table)
