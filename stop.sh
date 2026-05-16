#!/bin/bash
cd "$(dirname "$0")"
echo "🛑 停止集群..."
docker compose down

# 清理残留 lock 文件（崩溃后常残留）
echo "🧹 清理残留 lock 文件..."
for agent_dir in agent_configs/*; do
    if [ -d "$agent_dir" ]; then
        rm -f "$agent_dir"/*.lock 2>/dev/null || true
    fi
done

echo "✅ 已停止"
