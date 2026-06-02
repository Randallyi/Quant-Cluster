"""Retry downloading pending NeurIPS 2025 papers."""
import sys
from pathlib import Path

from core.store import PaperStore
from sources.conference import NeurIPSSource


def retry_neurips_2025(db_path: str, raw_dir: str):
    store = PaperStore(db_path)
    pending = store.get_pending("neurips_2025", limit=10000)
    if not pending:
        print("No pending papers for neurips_2025")
        return

    print(f"Found {len(pending)} pending papers for neurips_2025")

    source = NeurIPSSource(year=2025)

    downloaded = failed = 0
    for meta in pending:
        year = meta.year or 2025
        dest_dir = Path(raw_dir) / "neurips_2025" / str(year)
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
    retry_neurips_2025("/workspace/papers/downloads.db", "/workspace/papers/raw")
