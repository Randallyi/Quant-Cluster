import argparse
import os
import sys
import json
from pathlib import Path
from datetime import datetime

from core.store import PaperStore
from core.scheduler import Scheduler
from sources.arxiv import ArxivSource
from sources.core_ac import CoreSource
from sources.elsevier import ElsevierSource
from sources.wiley import WileySource
from sources.conference import NeurIPSSource
from sources.aistats import AistatsSource


def _expand_env(value):
    """递归解析字符串中的 ${ENV_VAR} 为环境变量值。"""
    if isinstance(value, str):
        if value.startswith("${") and value.endswith("}"):
            env_name = value[2:-1]
            return os.environ.get(env_name, "")
        return value
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config(path: Path) -> dict:
    import yaml
    with open(path) as f:
        raw = yaml.safe_load(f)
    return _expand_env(raw)


def build_sources(config: dict):
    sources = []
    src_cfg = config.get("sources", {})
    
    for name, cfg in src_cfg.items():
        if not cfg.get("enabled", False):
            continue
        if name.startswith("arxiv_"):
            cat = cfg["categories"][0]
            mode = cfg.get("backfill", {}).get("mode", "api")
            sources.append(ArxivSource(category=cat, backfill_mode=mode))
        elif name == "core_ac":
            key = config["api_keys"].get("core_ac", "")
            sources.append(CoreSource(api_key=key, queries=cfg["queries"], year_from=cfg.get("year_from", 2010)))
        elif name == "elsevier":
            key = config["api_keys"].get("elsevier", "")
            sources.append(ElsevierSource(api_key=key, journals=cfg["journals"], year_from=cfg.get("year_from", 2010)))
        elif name == "wiley":
            token = config["api_keys"].get("wiley_tdm", "")
            sources.append(WileySource(tdm_token=token, journals=cfg["journals"], year_from=cfg.get("year_from", 2010)))
        elif name == "neurips":
            sources.append(NeurIPSSource(year=datetime.now().year - 1))
        elif name == "aistats":
            sources.append(AistatsSource(year=cfg.get("year", datetime.now().year), volume=cfg.get("volume", 238)))
    return sources


def cmd_scan(args):
    config = load_config(Path(__file__).parent / "config.yaml")
    raw_dir = Path(config["storage"]["raw_dir"])
    db_path = Path(config["storage"]["db_path"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    store = PaperStore(db_path)
    sources = build_sources(config)
    if args.sources:
        names = set(args.sources.split(","))
        sources = [s for s in sources if s.name in names]
    
    scheduler = Scheduler(sources, config)
    results = []
    for source in scheduler.get_due_sources(store):
        result = scheduler.run_source(source, store, raw_dir)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))
    
    if args.report:
        summary = {
            "run_id": datetime.now().strftime("%Y-%m-%d-%H%M%S"),
            "sources": results,
            "total_new": sum(r["new"] for r in results),
            "total_downloaded": sum(r["downloaded"] for r in results),
            "total_failed": sum(r["failed"] for r in results),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))


def cmd_stats(args):
    config = load_config(Path(__file__).parent / "config.yaml")
    db_path = Path(config["storage"]["db_path"])
    store = PaperStore(db_path)
    cursor = store.conn.execute("""
        SELECT source, status, COUNT(*) as cnt FROM papers
        GROUP BY source, status
    """)
    for row in cursor.fetchall():
        print(f"{row['source']:20s} {row['status']:12s} {row['cnt']:4d}")


def main():
    parser = argparse.ArgumentParser(description="Paper Downloader")
    sub = parser.add_subparsers(dest="cmd")
    
    p_scan = sub.add_parser("scan", help="Scan and download papers")
    p_scan.add_argument("--sources", help="Comma-separated source names")
    p_scan.add_argument("--report", action="store_true", help="Output JSON summary")
    p_scan.add_argument("--layer", choices=["api"], help="Filter by layer")
    p_scan.set_defaults(func=cmd_scan)
    
    p_stats = sub.add_parser("stats", help="Show download statistics")
    p_stats.add_argument("--source", help="Filter by source name")
    p_stats.set_defaults(func=cmd_stats)
    
    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
