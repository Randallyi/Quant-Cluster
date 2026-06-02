"""Retry downloading pending papers for a given source."""
import sys
from pathlib import Path

from core.store import PaperStore
from sources.arxiv import ArxivSource


def retry_pending(source_name: str, db_path: str, raw_dir: str):
    store = PaperStore(db_path)
    pending = store.get_pending(source_name, limit=1000)
    if not pending:
        print(f"No pending papers for {source_name}")
        return

    print(f"Found {len(pending)} pending papers for {source_name}")

    # Build source instance
    source = ArxivSource(category="q-fin.TR", backfill_mode="api")

    downloaded = failed = 0
    for meta in pending:
        year = meta.year or 2026
        dest_dir = Path(raw_dir) / source_name / str(year)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / meta.suggested_filename()
        try:
            source.download(meta, dest_path)
            store.mark_downloaded(meta.id, str(dest_path))
            downloaded += 1
            print(f"  OK: {meta.source_id}")
        except Exception as e:
            store.mark_failed(meta.id, str(e))
            failed += 1
            print(f"  FAIL: {meta.source_id} — {e}")

    print(f"\nDone. Downloaded: {downloaded}, Failed: {failed}")


if __name__ == "__main__":
    retry_pending("arxiv_qfin_tr", "/workspace/papers/downloads.db", "/workspace/papers/raw")
