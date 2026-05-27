#!/bin/bash
# Quant Cluster Launcher for macOS
set -e

cd "$(dirname "$0")"

# ── 纯净启动模式 ────────────────────────────────────
CLEAN_MODE=false
if [ "$1" = "--clean" ] || [ "$1" = "-c" ]; then
    CLEAN_MODE=true
    echo "🧹 纯净启动模式：先重置状态，再启动集群..."
    bash "$(dirname "$0")/reset.sh"
    echo ""
fi

echo "🐳 启动 Hermes 量化集群..."

# 1. 检查 Docker
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker Desktop 未启动，请先打开 Docker Desktop"
    exit 1
fi

# 2. 检查 IB Gateway
if ! lsof -Pi :7497 > /dev/null 2>&1; then
    echo "⚠️  IB Gateway 未检测到在端口 7497 运行"
    echo "   请先启动 IB Gateway 并配置 Trusted IP: 192.168.65.0/24"
    echo "   下载地址: https://www.interactivebrokers.com/en/index.php?f=16457"
    exit 1
fi

echo "✅ IB Gateway 检测到在端口 7497"

# 3. 加载环境变量
export $(grep -v '^#' .env | xargs)

# 4. 启动 Docker Compose（包含 data_router + 5 个 Hermes + Redis）
echo "📦 启动 Docker Compose..."
docker compose up -d --force-recreate

# 5. 等待 data_router 就绪
echo "⏳ 等待 Data Router 连接 IB Gateway..."
until curl -s http://localhost:8888/health > /dev/null 2>&1; do
    echo "  等待 data_router..."
    sleep 3
done
echo "  ✅ Data Router 已连接 IB Gateway"

# 6. 等待 Hermes 实例就绪
echo "⏳ 等待 Hermes 实例启动（约 30 秒）..."
sleep 10
for port in 8642 8643 8644 8645 8646; do
    until curl -s http://localhost:$port/health > /dev/null 2>&1; do
        echo "  等待端口 $port..."
        sleep 3
    done
    echo "  ✅ 端口 $port 就绪"
done

# 6. 安装编排器依赖
echo "🐍 安装编排层依赖..."
cd orchestrator
pip install -r requirements.txt -q

# 7. Preflight 前置检查
echo "🔍 运行 Preflight 前置检查..."
if ! python3 -m orchestrator.preflight --mode=launch; then
    echo ""
    echo "❌ Preflight 未通过，集群启动已阻止"
    echo "   请修复上述问题后重新运行 ./launch.sh"
    exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅ 集群启动完成！"
echo ""
echo "  启动流水线:  python3 -m orchestrator.cli run --topic '你的研究主题'"
echo "  查看状态:     python3 -m orchestrator.cli status"
echo "  健康检查:     python orchestrator/orchestrator.py health"
echo ""
echo "  数据路由 (IB Gateway):"
echo "    Health:   http://localhost:8888/health"
echo "    API:      POST http://localhost:8888/data/historical"
echo ""
echo "  各 Agent API 端点:"
echo "    Hypothesis:      http://localhost:8642/v1"
echo "    Data Engineer:   http://localhost:8643/v1"
echo "    Quant Analyst:   http://localhost:8644/v1"
echo "    Risk Auditor:    http://localhost:8645/v1"
echo "    Strategy Writer: http://localhost:8646/v1"
echo "═══════════════════════════════════════════════════════"
