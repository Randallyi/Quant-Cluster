"""Retry downloading pending Elsevier papers."""
import os
import sys
from pathlib import Path

from core.store import PaperStore
from sources.elsevier import ElsevierSource


def retry_elsevier(db_path: str, raw_dir: str):
    api_key = os.environ.get("ELSEVIER_API_KEY")
    if not api_key:
        print("ERROR: ELSEVIER_API_KEY not set")
        sys.exit(1)

    store = PaperStore(db_path)
    pending = store.get_pending("elsevier", limit=1000)
    if not pending:
        print("No pending papers for elsevier")
        return

    print(f"Found {len(pending)} pending papers for elsevier")

    source = ElsevierSource(
        api_key=api_key,
        journals=["Journal of Financial Economics", "Journal of Banking and Finance", "Journal of Empirical Finance"],
        year_from=2010,
    )

    downloaded = failed = 0
    for meta in pending:
        year = meta.year or 2026
        dest_dir = Path(raw_dir) / "elsevier" / str(year)
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
    retry_elsevier("/workspace/papers/downloads.db", "/workspace/papers/raw")
