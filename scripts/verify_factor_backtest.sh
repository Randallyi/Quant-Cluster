#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Step 1: List available factors ==="
python3 tools/factor_tool.py --action list

echo ""
echo "=== Step 2: Bench academic_carhart_mom ==="
TMP_DIR=$(mktemp -d)
trap "rm -rf $TMP_DIR" EXIT

# Create synthetic ohlcv panel
python3 << EOF
import numpy as np
import pandas as pd

dates = pd.date_range("2023-01-01", periods=300, freq="D")
symbols = ["SPY", "QQQ"]
np.random.seed(42)

data = {}
for sym in symbols:
    base = 100 + np.cumsum(np.random.randn(300) * 0.5)
    data[(sym, "open")] = base + np.random.randn(300) * 0.1
    data[(sym, "high")] = base + abs(np.random.randn(300)) * 0.2
    data[(sym, "low")] = base - abs(np.random.randn(300)) * 0.2
    data[(sym, "close")] = base
    data[(sym, "volume")] = np.random.randint(1_000_000, 10_000_000, 300)

df = pd.DataFrame(data, index=dates)
df.columns = pd.MultiIndex.from_tuples(df.columns)
df.to_parquet("$TMP_DIR/ohlcv_panel.parquet")
print(f"Created panel: {df.shape}")
EOF

python3 tools/factor_tool.py \
    --action bench \
    --factor academic_carhart_mom \
    --data "$TMP_DIR/ohlcv_panel.parquet" \
    --fwd-days 5 \
    --out-dir "$TMP_DIR/bench"

echo ""
echo "=== Step 3: Signal academic_carhart_mom ==="
python3 tools/factor_tool.py \
    --action signal \
    --factor academic_carhart_mom \
    --data "$TMP_DIR/ohlcv_panel.parquet" \
    --params '{"direction":"long_short","top_pct":0.2}' \
    --out-dir "$TMP_DIR/signal"

echo ""
echo "=== Step 4: Bench category academic ==="
python3 tools/factor_tool.py \
    --action bench_category \
    --category academic \
    --data "$TMP_DIR/ohlcv_panel.parquet" \
    --out-dir "$TMP_DIR/bench_cat"

echo ""
echo "=== Verification complete ==="
echo "Bench output: $TMP_DIR/bench/"
echo "Signal output: $TMP_DIR/signal/"
echo "Category bench output: $TMP_DIR/bench_cat/"
