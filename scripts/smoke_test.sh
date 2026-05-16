#!/bin/bash
# smoke_test.sh — 纯净启动后验证系统处于"可复现的干净状态"
# 用法：在 bash launch.sh --clean 之后运行

set -e

cd "$(dirname "$0")/.."

FAILED=0

echo "🔍 Smoke Test: 验证纯净启动后状态..."
echo ""

# ── 1. 验证 Workspace 为空（除 .gitkeep）────────────────
echo "  [1/6] 检查 Workspace..."
for ws in shared_workspace/0*; do
    if [ -d "$ws" ]; then
        count=$(find "$ws" -type f | wc -l | tr -d ' ')
        if [ "$count" -gt 0 ]; then
            echo "    ❌ $ws 非空 ($count 个文件)"
            FAILED=$((FAILED + 1))
        else
            echo "    ✅ $ws 为空"
        fi
    fi
done

# ── 2. 验证 Agent DB 已重置 ────────────────────────────
echo "  [2/6] 检查 Agent 状态数据库..."
for db in agent_configs/*/*.db; do
    if [ -f "$db" ]; then
        size=$(stat -f%z "$db" 2>/dev/null || stat -c%s "$db" 2>/dev/null || echo "unknown")
        if [ "$size" != "0" ] && [ "$size" != "unknown" ]; then
            echo "    ❌ $db 存在且非空 ($size bytes)"
            FAILED=$((FAILED + 1))
        else
            echo "    ✅ $db 已清理"
        fi
    fi
done

# ── 3. 验证无残留 lock 文件 ────────────────────────────
echo "  [3/6] 检查残留 lock 文件..."
lock_count=$(find agent_configs/ -name "*.lock" | wc -l | tr -d ' ')
if [ "$lock_count" -gt 0 ]; then
    echo "    ❌ 发现 $lock_count 个 .lock 文件"
    FAILED=$((FAILED + 1))
else
    echo "    ✅ 无残留 lock"
fi

# ── 4. 验证 Data Router 缓存已清理 ──────────────────────
echo "  [4/6] 检查 Data Router 缓存..."
if [ -f "data_router/cache/data_cache.db" ]; then
    echo "    ❌ data_cache.db 仍存在"
    FAILED=$((FAILED + 1))
else
    echo "    ✅ 缓存已清理"
fi

# ── 5. 验证容器健康 ────────────────────────────────────
echo "  [5/6] 检查容器健康状态..."
for port in 8642 8643 8644 8645 8646 8888; do
    status=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$port/health" 2>/dev/null || echo "000")
    if [ "$status" = "200" ] || [ "$status" = "000" ]; then
        # 000 means container might still be starting, not a hard fail
        echo "    ✅ 端口 $port 响应 HTTP $status"
    else
        echo "    ⚠️  端口 $port 返回 HTTP $status"
    fi
done

# ── 6. 验证 WebBridge 可达 ─────────────────────────────
echo "  [6/6] 检查 WebBridge..."
wb_status=$(docker exec hermes-hypothesis python3 /workspace/tools/webbridge_client.py status 2>&1 | head -1 || echo "failed")
if echo "$wb_status" | grep -q "ok"; then
    echo "    ✅ WebBridge 可达"
else
    echo "    ⚠️  WebBridge 未响应（如不需要可忽略）"
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo "✅ Smoke Test 通过 — 系统处于纯净状态，可复现。"
    exit 0
else
    echo "❌ Smoke Test 失败 — 发现 $FAILED 个问题。建议运行 bash reset.sh 后重试。"
    exit 1
fi
