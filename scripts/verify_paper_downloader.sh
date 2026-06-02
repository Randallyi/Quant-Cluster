#!/bin/bash
# scripts/verify_paper_downloader.sh
set -e

cd "/Users/yihaoyang/VScode workspace/quant-cluster"

echo "=== 1. Verify module imports ==="
cd tools/paper_downloader
python3 -c "from core.models import PaperMeta; from core.store import PaperStore; from sources.base import Source; print('OK')"

echo "=== 2. Run unit tests ==="
python3 -m pytest tests/ -v --tb=short

echo "=== 3. Verify CLI help ==="
PYTHONPATH="..:$PYTHONPATH" python3 -m paper_downloader --help

echo "=== 4. Verify config syntax ==="
python3 -c "import yaml; yaml.safe_load(open('config.yaml')); print('config.yaml OK')"

echo "=== 5. Verify Agent config ==="
python3 -c "import yaml; yaml.safe_load(open('../../agent_configs/paper_downloader/config.yaml')); print('Agent config OK')"

echo "=== All checks passed ==="
