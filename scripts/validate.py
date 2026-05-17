#!/usr/bin/env python3
"""
Quant Cluster Agent Configuration Validator

Validates all agent configs, DAG consistency, and cross-references.
Inspired by Anthropic financial-services/scripts/check.py.

Usage:
    python scripts/validate.py              # validate all, exit 0/1
    python scripts/validate.py --fix        # auto-fix simple issues
    python scripts/validate.py --verbose    # detailed output
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
AGENT_CONFIGS = ROOT / "agent_configs"
ORCHESTRATOR = ROOT / "orchestrator"
errors: List[str] = []
warnings: List[str] = []
fixed: List[str] = []
checked = 0

# ── Git hooks auto-install (reference: Anthropic check.py) ─────────

def ensure_hooks_installed() -> None:
    """Point git at .githooks so the pre-commit hook runs."""
    want = ".githooks"
    try:
        cur = subprocess.run(
            ["git", "-C", str(ROOT), "config", "--get", "core.hooksPath"],
            capture_output=True, text=True,
        ).stdout.strip()
        if cur != want:
            subprocess.run(
                ["git", "-C", str(ROOT), "config", "core.hooksPath", want],
                check=True, capture_output=True,
            )
            print(f"[validate.py] installed git hooks (core.hooksPath -> {want})")
    except (subprocess.SubprocessError, OSError):
        pass


# ── Helpers ─────────────────────────────────────────────────────────

def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def parse_frontmatter(md_path: Path) -> Tuple[Optional[dict], str]:
    """Extract YAML frontmatter and remaining body from a markdown file."""
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text
    try:
        # Try PyYAML first, fall back to simple parser
        import yaml
        fm = yaml.safe_load(parts[1])
        return fm, parts[2]
    except ImportError:
        # Minimal YAML parser for frontmatter without external deps
        return _simple_parse_yaml(parts[1]), parts[2]
    except Exception as e:
        err(f"frontmatter YAML parse: {rel(md_path)}: {e}")
        return None, text


def _simple_parse_yaml(text: str) -> Optional[dict]:
    """Minimal YAML parser for simple frontmatter (no nested lists/dicts)."""
    result = {}
    current_key = None
    current_list = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # List item
        if stripped.startswith("- "):
            if current_list is not None:
                current_list.append(stripped[2:].strip().strip('"\''))
            continue
        # Key: value
        if ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                # Might be a list start
                current_key = key
                current_list = []
                result[key] = current_list
            else:
                result[key] = val.strip('"\'')
                current_list = None
    return result


# ── Load DAG (best-effort, no hard dependency) ──────────────────────

def load_dag() -> Tuple[dict, dict, list]:
    """Load DAG from orchestrator/core/dag.py if available."""
    dag_path = ORCHESTRATOR / "core" / "dag.py"
    if not dag_path.exists():
        return {}, {}, []
    # exec the module to get AGENTS, DAG, EXECUTION_ORDER
    # Provide __file__ so dag.py's Path(__file__) works
    namespace = {"__file__": str(dag_path), "Path": Path}
    try:
        exec(dag_path.read_text(), namespace)
    except Exception as e:
        warn(f"Could not load DAG: {e}")
        return {}, {}, []
    return (
        namespace.get("AGENTS", {}),
        namespace.get("DAG", {}),
        namespace.get("EXECUTION_ORDER", []),
    )


# ── Checkers ────────────────────────────────────────────────────────

def check_required_files(agent_dir: Path) -> None:
    """Check each agent directory has required files."""
    global checked
    checked += 1
    for req in ("SOUL.md", "config.yaml"):
        p = agent_dir / req
        if not p.is_file():
            err(f"missing required file: {rel(p)}")


def check_config_yaml(agent_dir: Path) -> None:
    """Validate config.yaml is parseable YAML."""
    global checked
    p = agent_dir / "config.yaml"
    if not p.is_file():
        return
    checked += 1
    try:
        text = p.read_text(encoding="utf-8")
        # Best-effort: lines with colons should be valid YAML-like
        # Real YAML parsing requires pyyaml; we warn if not available
        try:
            import yaml
            yaml.safe_load(text)
        except ImportError:
            # Basic syntax check: balanced braces/brackets
            _basic_yaml_sanity(text, p)
    except Exception as e:
        err(f"config.yaml parse: {rel(p)}: {e}")


def _basic_yaml_sanity(text: str, path: Path) -> None:
    """Basic structural checks when PyYAML is unavailable."""
    lines = text.splitlines()
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Check for obvious issues like tabs after spaces (common YAML pitfall)
        if "\t" in line and not stripped.startswith("#"):
            warn(f"config.yaml: {rel(path)}:{i} contains tab characters (may break YAML parsing)")


def check_soul_frontmatter(agent_dir: Path) -> None:
    """Check SOUL.md frontmatter completeness."""
    global checked
    p = agent_dir / "SOUL.md"
    if not p.is_file():
        return
    checked += 1
    fm, body = parse_frontmatter(p)
    if fm is None:
        err(f"frontmatter: {rel(p)}: missing or invalid YAML frontmatter (must start with '---')")
        return
    for key in ("name", "description", "output_spec"):
        if key not in fm or not fm[key]:
            err(f"frontmatter: {rel(p)}: missing or empty '{key}'")

    # Check output_spec contains bilingual pairs
    output_spec = fm.get("output_spec", [])
    if isinstance(output_spec, list):
        md_files = [item for item in output_spec if isinstance(item, str) and item.endswith(".md")]
        for md in md_files:
            if "_en.md" in md:
                continue  # skip english files
            # Check if there's a corresponding _en.md
            en_version = md.replace(".md", "_en.md")
            if en_version not in output_spec:
                # Also check for patterns with {slug} etc.
                has_en_pair = any(
                    "_en.md" in item for item in output_spec if isinstance(item, str)
                )
                if not has_en_pair:
                    warn(f"frontmatter: {rel(p)}: output_spec may be missing English pair for '{md}'")


def check_dag_consistency(agents: dict, dag: dict, execution_order: list) -> None:
    """Check DAG references resolve to real agent directories and workspaces exist."""
    global checked
    if not dag:
        return
    checked += 1
    # Check all agents in DAG have config dirs
    for agent_name in dag:
        agent_dir = AGENT_CONFIGS / agent_name
        if not agent_dir.is_dir():
            err(f"DAG: agent '{agent_name}' has no config directory at {rel(agent_dir)}")

    # Check workspace paths exist
    for agent_name, info in agents.items():
        ws = info.get("workspace")
        if ws:
            ws_path = ROOT / "shared_workspace" / ws
            # Workspace dirs are created at runtime; check the path pattern is valid
            if "/" in ws or "\\" in ws:
                err(f"DAG: agent '{agent_name}' workspace '{ws}' contains path separators")

    # Check execution order matches DAG dependencies
    seen = set()
    for agent in execution_order:
        deps = dag.get(agent, {}).get("deps", [])
        for dep in deps:
            if dep not in seen:
                err(f"DAG: execution order violation — '{agent}' depends on '{dep}' but '{dep}' comes later")
        seen.add(agent)


def check_output_spec_consistency(agents: dict, dag: dict) -> None:
    """Check SOUL.md output_spec roughly matches DAG output_files."""
    global checked
    for agent_name, dag_info in dag.items():
        agent_dir = AGENT_CONFIGS / agent_name
        soul = agent_dir / "SOUL.md"
        if not soul.is_file():
            continue
        checked += 1
        fm, _ = parse_frontmatter(soul)
        if fm is None:
            continue
        soul_outputs = fm.get("output_spec", [])
        dag_outputs = dag_info.get("output_files", [])
        if not isinstance(soul_outputs, list):
            continue
        # Check that .agent_checkpoint.json is in both
        has_checkpoint_soul = any(".agent_checkpoint.json" in str(o) for o in soul_outputs)
        has_checkpoint_dag = any(".agent_checkpoint.json" in p for p in dag_outputs)
        if has_checkpoint_dag and not has_checkpoint_soul:
            warn(f"output_spec: {rel(soul)}: DAG requires .agent_checkpoint.json but output_spec doesn't mention it")


def check_cross_references(agent_dir: Path, agents: dict, dag: dict) -> None:
    """Check that workspace paths referenced in SOUL.md exist in DAG."""
    global checked
    p = agent_dir / "SOUL.md"
    if not p.is_file():
        return
    checked += 1
    text = p.read_text(encoding="utf-8")
    # Find all /workspace/XX_xxx/ references
    workspaces = set(re.findall(r"/workspace/([0-9]{2}_[a-z_]+)/", text, re.IGNORECASE))
    dag_workspaces = {
        info.get("workspace") for info in agents.values()
        if isinstance(info, dict) and "workspace" in info
    }
    for ws in workspaces:
        if ws not in dag_workspaces:
            warn(f"cross-ref: {rel(p)}: references workspace '/workspace/{ws}/' not found in DAG")


# ── Fixers ──────────────────────────────────────────────────────────

def fix_missing_frontmatter(agent_dir: Path) -> bool:
    """Auto-add minimal frontmatter if missing."""
    p = agent_dir / "SOUL.md"
    if not p.is_file():
        return False
    text = p.read_text(encoding="utf-8")
    if text.startswith("---"):
        return False
    agent_name = agent_dir.name
    # Infer output spec from DAG
    dag_outputs = []
    try:
        _, dag, _ = load_dag()
        if agent_name in dag:
            dag_outputs = dag[agent_name].get("output_files", [])
    except Exception:
        pass
    output_lines = "\n".join(f"  - {o}" for o in dag_outputs) if dag_outputs else "  - (see DAG)"
    frontmatter = f"""---
name: {agent_name}
description: |
  (TODO: add description)
output_spec:
{output_lines}
dependencies:
  - (TODO: add dependencies)
---

"""
    p.write_text(frontmatter + text, encoding="utf-8")
    fixed.append(f"added frontmatter to {rel(p)}")
    return True


# ── Main ────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Quant Cluster Agent Config Validator")
    parser.add_argument("--fix", action="store_true", help="Auto-fix simple issues")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--install-hooks", action="store_true", help="Install git hooks and exit")
    args = parser.parse_args()

    if args.install_hooks:
        ensure_hooks_installed()
        return 0

    # Auto-install hooks on first run (best effort)
    ensure_hooks_installed()

    # Load DAG
    agents, dag, execution_order = load_dag()

    # Collect agent directories
    agent_dirs = sorted(
        [d for d in AGENT_CONFIGS.iterdir() if d.is_dir() and not d.name.startswith(".")]
    )

    # ── Run checks ──────────────────────────────────────────────────
    for agent_dir in agent_dirs:
        check_required_files(agent_dir)
        check_config_yaml(agent_dir)
        check_soul_frontmatter(agent_dir)
        check_cross_references(agent_dir, agents, dag)

    if dag:
        check_dag_consistency(agents, dag, execution_order)
        check_output_spec_consistency(agents, dag)

    # ── Auto-fixes ──────────────────────────────────────────────────
    if args.fix:
        for agent_dir in agent_dirs:
            fix_missing_frontmatter(agent_dir)
        # Re-run checks after fix
        errors.clear()
        warnings.clear()
        for agent_dir in agent_dirs:
            check_required_files(agent_dir)
            check_config_yaml(agent_dir)
            check_soul_frontmatter(agent_dir)
            check_cross_references(agent_dir, agents, dag)
        if dag:
            check_dag_consistency(agents, dag, execution_order)
            check_output_spec_consistency(agents, dag)

    # ── Report ──────────────────────────────────────────────────────
    if args.verbose or fixed:
        print(f"\nChecked {checked} item(s) across {len(agent_dirs)} agent(s).\n")

    if fixed:
        print("Fixed:")
        for f in fixed:
            print(f"  ✓ {f}")
        print()

    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"  ⚠ {w}")
        print()

    if errors:
        print(f"FAIL — {len(errors)} error(s):\n")
        for e in errors:
            print(f"  ✗ {e}")
        print("\nRun with --fix to auto-fix simple issues.")
        return 1

    print("OK — all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
