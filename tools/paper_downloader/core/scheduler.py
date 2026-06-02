from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from core.store import PaperStore
from sources.base import Source

FREQUENCY_DELTA = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
    "yearly": timedelta(days=365),
}


def should_run(frequency: str, last_run: Optional[datetime]) -> bool:
    if last_run is None:
        return True
    delta = FREQUENCY_DELTA.get(frequency, timedelta(days=1))
    return datetime.now() - last_run >= delta


class Scheduler:
    def __init__(self, sources: List[Source], config: Dict[str, Any]):
        self.sources = {s.name: s for s in sources}
        self.config = config

    def get_due_sources(self, store: Optional[PaperStore] = None) -> List[Source]:
        due = []
        for name, source in self.sources.items():
            src_cfg = self.config.get("sources", {}).get(name, {})
            if not src_cfg.get("enabled", True):
                continue
            # For now, always run on-demand or if no store tracking
            due.append(source)
        return due

    def run_source(self, source: Source, store: PaperStore, raw_dir: Path) -> dict:
        since = store.get_latest_published_at(source.name)
        if since is None:
            # Default to last 7 days for incremental scan; backfill should be explicit
            since = datetime.now(timezone.utc) - timedelta(days=7)
        elif since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)

        metas = source.scan(since)
        new_metas = store.dedupe_and_insert(metas)

        # Helper: check if source supports selective auto-download
        has_filter = hasattr(source, 'should_auto_download')

        # Gather all pending records (existing + newly inserted)
        all_pending = []
        while True:
            batch = store.get_pending(source.name, limit=1000)
            if not batch:
                break
            all_pending.extend(batch)

        # Split into catalogue-only and auto-download
        to_catalogue = []
        to_download = []
        for meta in all_pending:
            if has_filter and not source.should_auto_download(meta.title):
                to_catalogue.append(meta.id)
            else:
                to_download.append(meta)

        # Bulk catalogue non-relevant papers (single transaction = fast)
        catalogued = store.bulk_catalogue(to_catalogue, "title-filter")

        # Download relevant papers one by one (respects rate limits)
        downloaded = failed = 0
        for meta in to_download:
            year = meta.year or datetime.now().year
            dest_dir = raw_dir / source.name / str(year)
            dest_path = dest_dir / meta.suggested_filename()
            try:
                source.download(meta, dest_path)
                store.mark_downloaded(meta.id, str(dest_path))
                downloaded += 1
            except Exception as e:
                store.mark_failed(meta.id, str(e))
                failed += 1

        return {
            "source": source.name,
            "found": len(metas),
            "new": len(new_metas),
            "pending": len(pending_ids),
            "catalogued": catalogued,
            "downloaded": downloaded,
            "failed": failed,
        }
