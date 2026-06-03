"""
管理 scan_state.json —— 扫描器进度的唯一数据源。
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


DEFAULT_STATE = {
    "last_updated": "",
    "total_papers": 0,
    "stats": {
        "pending": 0,
        "preprocessing": 0,
        "scanning": 0,
        "completed": 0,
        "failed": 0,
        "skipped": 0,
    },
    "config": {
        "max_concurrent": 3,
        "priority_rules": ["source_tier", "year_desc", "added_at_desc"],
    },
    "papers": {},
}

TIER_PRIORITY = {"journal": 0, "ssrn": 1, "arxiv": 2}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ScanState:
    def __init__(self, state_path: Path):
        self.state_path = state_path
        if state_path.exists():
            self.data = json.loads(state_path.read_text(encoding="utf-8"))
        else:
            self.data = json.loads(json.dumps(DEFAULT_STATE))
            self.data["last_updated"] = _now()
            self.save()

    def add_paper(self, filepath: str, doc_id: str) -> None:
        """添加新论文，状态为 pending。"""
        self.data["papers"][doc_id] = {
            "filepath": filepath,
            "status": "pending",
            "added_at": _now(),
        }
        self.data["total_papers"] = len(self.data["papers"])
        self._recalc_stats()
        self.save()

    def mark_status(self, doc_id: str, status: str, **kwargs) -> None:
        """更新论文状态和可选字段。"""
        if doc_id not in self.data["papers"]:
            raise KeyError(f"Paper {doc_id} not found in state")

        old_status = self.data["papers"][doc_id].get("status")
        self.data["papers"][doc_id]["status"] = status
        self.data["papers"][doc_id].update(kwargs)

        # Update last_updated on the paper entry if completing
        if status in ("completed", "failed", "skipped"):
            self.data["papers"][doc_id]["scanned_at"] = _now()

        self._recalc_stats()
        self.save()

    def get_pending(self) -> List[Dict]:
        """返回 pending 论文列表，按 source_tier > year 排序。"""
        pending = [
            {"doc_id": doc_id, **paper}
            for doc_id, paper in self.data["papers"].items()
            if paper.get("status") == "pending"
        ]
        pending.sort(
            key=lambda p: (
                TIER_PRIORITY.get(p.get("source_tier", "arxiv"), 99),
                -(p.get("year", 0) or 0),
            )
        )
        return pending

    def get_running(self) -> List[Dict]:
        """返回 scanning 状态的论文列表。"""
        return [
            {"doc_id": doc_id, **paper}
            for doc_id, paper in self.data["papers"].items()
            if paper.get("status") == "scanning"
        ]

    def save(self) -> None:
        """持久化到磁盘。"""
        self.data["last_updated"] = _now()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _recalc_stats(self) -> None:
        """重新计算状态统计。"""
        stats = {k: 0 for k in DEFAULT_STATE["stats"]}
        for paper in self.data["papers"].values():
            status = paper.get("status", "pending")
            if status in stats:
                stats[status] += 1
        self.data["stats"] = stats
