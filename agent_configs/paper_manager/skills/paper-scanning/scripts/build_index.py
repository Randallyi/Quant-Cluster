"""
从 scan_state.json 生成 scanned/index.json。
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


TIER_PRIORITY = {"journal": 0, "ssrn": 1, "arxiv": 2}


def build_index(scan_state_path: Path, output_path: Path) -> None:
    """读取 scan_state.json，过滤已完成论文，生成 index.json。"""
    if not scan_state_path.exists():
        raise FileNotFoundError(f"scan_state not found: {scan_state_path}")

    scan_state = json.loads(scan_state_path.read_text(encoding="utf-8"))
    papers_map = scan_state.get("papers", {})

    entries: List[Dict] = []
    by_tier: Dict[str, int] = {"journal": 0, "ssrn": 0, "arxiv": 0}
    by_type: Dict[str, int] = {}

    for doc_id, paper in papers_map.items():
        if paper.get("status") != "completed":
            continue

        card_data = paper.get("card_data", {})
        source_tier = card_data.get("source_tier") or paper.get("source_tier", "arxiv")
        paper_type = card_data.get("paper_type") or paper.get("paper_type", "other")

        entry = {
            "doc_id": doc_id,
            "title": card_data.get("title", ""),
            "authors": card_data.get("authors", []),
            "year": card_data.get("year", 0),
            "source": card_data.get("source", ""),
            "source_tier": source_tier,
            "paper_type": paper_type,
            "credibility_score": card_data.get("credibility_score", 0),
            "credibility_tier": card_data.get("credibility_tier", ""),
            "card_paths": {
                "zh": f"scanned/{doc_id}/card.md",
                "en": f"scanned/{doc_id}/card_en.md",
            },
            "scanned_at": paper.get("scanned_at", ""),
        }

        quant_summary = card_data.get("quant_summary")
        if quant_summary is not None:
            entry["quant_summary"] = quant_summary

        entries.append(entry)

        # Update stats
        by_tier[source_tier] = by_tier.get(source_tier, 0) + 1
        by_type[paper_type] = by_type.get(paper_type, 0) + 1

    # Sort: source_tier priority > credibility_score desc > year desc
    entries.sort(
        key=lambda e: (
            TIER_PRIORITY.get(e["source_tier"], 99),
            -e["credibility_score"],
            -e["year"],
        )
    )

    index = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_scanned": len(entries),
        "by_tier": by_tier,
        "by_type": by_type,
        "papers": entries,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
