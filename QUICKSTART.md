# Quant Cluster — 快速开始指南

> 从 GitHub clone 到跑通第一个 pipeline 的完整步骤

---

## 1. 环境准备

### 必需软件

| 软件 | 用途 | 安装方式 |
|------|------|---------|
| **Docker Desktop** | 运行 6 个容器（Data Router + 5 Agents） | [官网下载](https://www.docker.com/products/docker-desktop) |
| **IB Gateway** | 连接 Interactive Brokers 获取市场数据 | [官网下载](https://www.interactivebrokers.com/en/index.php?f=16457) |
| **Kimi Code CLI** | 入口指挥官 + WebBridge 浏览器桥接 | [安装指南](https://www.kimi.com/code/docs/installation) |

### API Keys

| Key | 用途 | 获取地址 |
|-----|------|---------|
| **Kimi Code API Key** | 5 个 Agent 的 LLM 大脑 | [kimi.com/code](https://www.kimi.com/code/docs/third-party-tools/other-coding-agents.html) |
| **Tavily API Key** | Hypothesis Agent 文献搜索 | [tavily.com](https://tavily.com) |

> 💡 **Kimi Code API 和 Tavily 的关系**：Tavily 负责搜索候选链接，Kimi Code (via WebBridge) 负责获取需登录网站的全文。两者配合，不是替代关系。

---

## 2. 下载项目

```bash
git clone https://github.com/Randallyi/Quant-Cluster.git
cd Quant-Cluster
```

---

## 3. 配置环境

```bash
# 1. 复制环境变量模板
cp .env.example .env

# 2. 编辑 .env，填入你的 API keys
# ANTHROPIC_BASE_URL=https://api.kimi.com/coding/
# ANTHROPIC_API_KEY=sk-your-key
# TAVILY_API_KEY=tvly-your-key
```

---

## 4. 启动依赖服务

### 4.1 启动 IB Gateway

1. 打开 IB Gateway（Paper Trading 模式）
2. 设置 → API → 启用 "ActiveX and Socket Clients"
3. Socket 端口：**7497**
4. **取消勾选** "Read-Only API"（Agent 需要下单权限做回测验证）
5. **勾选** "Create API message log"
6. 信任 IP 范围添加：`192.168.65.0/24`（Docker 容器网段）

### 4.2 启动 WebBridge

WebBridge 是运行在宿主机上的 Chrome 浏览器守护进程，Agent 通过它访问需登录的网站。

```bash
# 启动 WebBridge（需要 Kimi Code CLI 已安装）
# 默认监听 host.docker.internal:10086
kimi webbridge start

# 验证状态
curl http://localhost:10086/status
```

> 🔴 **没有 WebBridge 的后果**：Hypothesis Agent 的文献调研会大幅降级，只能拿到 Tavily 的标题+摘要，无法访问 SSRN、QuantConnect、Seeking Alpha 的全文。

---

## 5. 启动 Quant Cluster

```bash
bash launch.sh
```

等 15-20 秒后验证：

```bash
python3 -m orchestrator.orchestrator health
```

期望看到 5 个 Agent 全部 ✅ Online。

---

## 6. 使用方式

### 方式 A：Kimi Code 自动模式（推荐）

安装项目自带的 skill：

```bash
ln -s $(pwd)/.kimi/skills/quant-cluster ~/.kimi/skills/quant-cluster
```

然后直接对话：

```
你: 研究一下 A 股行业轮动与宏观指标的桥接策略
Kimi Code: 🚀 正在启动 Quant Cluster pipeline...
         [检查容器 → 运行 hypothesis → data_engineer → ...]
         ✅ 已完成！
         
         📊 HTML 报告: shared_workspace/archive/run_2026xxxx/final_report.html
         📁 归档目录: shared_workspace/archive/run_2026xxxx/
```

Kimi Code 会自动：
- 检查容器状态，不在线则启动
- 运行 health check
- 调用 `orchestrator run --topic "..."`
- 等待 pipeline 完成
- 汇总结果给你

### 方式 B：CLI 手动模式

```bash
# 完整跑一个研究主题
python3 -m orchestrator.orchestrator run --topic "动量与反转的边界条件"

# Dry-run（不调用 Agent，验证流程连通性）
python3 -m orchestrator.orchestrator run --topic "测试" --dry-run

# 从中间 stage 恢复
python3 -m orchestrator.orchestrator run --topic "xxx" --from-stage quant_analyst

# 跳过归档（保留 workspace 所有文件）
python3 -m orchestrator.orchestrator run --topic "xxx" --skip-archive

# 流式输出（实时看 Agent 在干什么）
python3 -m orchestrator.orchestrator run --topic "xxx" --stream
```

---

## 7. 查看产物

```bash
# 历史 runs
python3 -m orchestrator.orchestrator status

# 打开最新的 HTML 报告
open shared_workspace/archive/run_*/final_report.html

# 查看归档结构
ls shared_workspace/archive/run_*/
```

---

## 8. 停止

```bash
bash stop.sh
```

---

## 常见问题

### Q1: `health` 检查显示某个 Agent Offline

```bash
# 重启单个 Agent
docker restart hermes-hypothesis   # 或 hermes-data / hermes-quant / hermes-risk / hermes-writer

# 如果端口被占用
lsof -i :8642  # 检查端口占用
```

### Q2: data_engineer 数据获取很慢

- 第一次请求会走 IBKR API（约 10-20 分钟）
- data_router 有 SQLite cache，同一 symbol 的第二次请求直接命中（毫秒级）
- cache 文件在 `./data_router/cache/data_cache.db`

### Q3: WebBridge 连接失败

```bash
# 检查 WebBridge 是否运行
curl http://localhost:10086/status

# 如果没运行，启动它
kimi webbridge start
```

### Q4: 怎么换研究主题？

直接改 `--topic` 参数即可。每个新 topic 会自动创建新的 run ID，旧的产物会被归档到 `shared_workspace/archive/`。

### Q5: 我想用 OpenAI / Claude 而不是 Kimi Code

修改 `agent_configs/*/config.yaml` 中的 `model` 配置，以及 `.env` 中的 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_API_KEY`。

---

## 下一步

- 想深入了解架构？看 `docs/superpowers/specs/2026-05-15-quant-cluster-hermes-ibkr-design.md`
- 想加第 6 个 Agent？参考 `CONTRIBUTING.md`（如果有的话）
- 有问题？开 GitHub Issue
