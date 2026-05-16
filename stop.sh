#!/bin/bash
cd "$(dirname "$0")"
echo "🛑 停止集群..."
docker compose down
echo "✅ 已停止"
