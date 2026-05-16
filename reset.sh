#!/bin/bash
# reset.sh — 一键重置 Quant Cluster 到"纯净状态"
# 用途：在重新运行 pipeline 前，清除所有跨 run 的残留状态
# 警告：这会删除所有历史运行状态，但保留 archive/ 中的报告备份

set -e

cd "$(dirname "$0")"

echo "🧹 Quant Cluster 纯净启动重置..."

# ── 1. 停止所有容器（保留镜像）──────────────────────
echo "  [1/6] 停止容器..."
docker compose down 2>/dev/null || true

# ── 2. 清理 Hermes Agent 状态数据库 ─────────────────
echo "  [2/6] 清理 Agent 状态数据库..."
for agent_dir in agent_configs/*; do
    if [ -d "$agent_dir" ]; then
        rm -f "$agent_dir"/*.db* 2>/dev/null || true
        rm -f "$agent_dir"/*.lock 2>/dev/null || true
        rm -f "$agent_dir"/auth.json 2>/dev/null || true
        rm -f "$agent_dir"/auth.lock 2>/dev/null || true
        rm -f "$agent_dir"/gateway_state.json 2>/dev/null || true
        rm -f "$agent_dir"/channel_directory.json 2>/dev/null || true
        rm -f "$agent_dir"/.skills_prompt_snapshot.json 2>/dev/null || true
        rm -rf "$agent_dir"/cache/* 2>/dev/null || true
        rm -rf "$agent_dir"/logs/* 2>/dev/null || true
        rm -rf "$agent_dir"/sessions/* 2>/dev/null || true
    fi
done

# ── 3. 清理 Data Router 缓存 ────────────────────────
echo "  [3/6] 清理 Data Router 缓存..."
rm -f data_router/cache/data_cache.db 2>/dev/null || true
rm -f data_router/cache/data_cache.db-* 2>/dev/null || true

# ── 4. 清理 Workspace（保留 archive/）───────────────
echo "  [4/6] 清理 Workspace..."
for ws_dir in shared_workspace/0* shared_workspace/orchestrator.db; do
    if [ -e "$ws_dir" ]; then
        rm -rf "$ws_dir" 2>/dev/null || true
    fi
done

# ── 5. 清理 Redis Volume ────────────────────────────
echo "  [5/6] 清理 Redis 持久化数据..."
docker volume rm quant-cluster_redis_data 2>/dev/null || true

# ── 6. 清理编排器本地状态 ───────────────────────────
echo "  [6/6] 清理 Orchestrator 状态..."
rm -f orchestrator/orchestrator.db 2>/dev/null || true
rm -f orchestrator/orchestrator.db-* 2>/dev/null || true

echo ""
echo "✅ 纯净重置完成。系统现在处于'首次运行'状态。"
echo "   下一步：bash launch.sh   启动集群"
echo "   或直接：bash launch.sh --clean   （集成模式，自动重置+启动）"
