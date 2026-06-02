# Paper Downloader Agent 设计规格

> 独立运行的论文批量下载器，定时从多个学术源抓取 OA 论文到本地，产出结构化元数据库，为后续 Paper Scanner 提供输入。
> 配套设计：[Paper Scanner Agent 设计规格](2026-05-28-paper-scanner-design.md)

---

## 1. 背景与目标

### 1.1 问题

Quant Cluster 现有的 Hypothesis Agent 负责"搜论文 → 读论文 → 生成假设"，但论文获取环节存在以下问题：

- **无自动化下载**：Agent 每次研究主题时才临时搜索，无法持续积累论文池
- **来源分散**：arXiv、SSRN、期刊 OA、会议论文等来源各自为政，没有统一入口
- **无法回溯**：期刊的历史 OA 内容（10-20 年）需要批量抓取，临时搜索做不到
- **与 Scanner 边界不清**：现有 Paper Scanner 设计假设论文已在本地，但没有 Downloader 来填充这个假设

### 1.2 设计目标

- 成为**独立的论文下载服务**，不依赖网络搜索时的临时抓取
- 支持**多源、分层频率**的定时扫描（高频每周 + 中频每月 + 低频回溯）
- 产出**结构化的元数据库**（SQLite），支持去重、增量、状态追踪
- **全开模式**：不设关键词过滤，直接拉各源最新全部 OA 内容，靠后续 Scanner 评分筛选
- 与 Paper Scanner 天然衔接：Scanner 直接读取 `shared_workspace/papers/raw/`

### 1.3 与 Paper Scanner 的边界

| 维度 | Paper Downloader | Paper Scanner |
|------|-----------------|---------------|
| 触发方式 | 定时 / 手动 | 定时 / 手动 |
| 输入 | 各学术源的 API / 网页 | 本地 PDF / HTML |
| 输出 | 原始 PDF + 元数据库 | 论文卡片 + 论文池索引 |
| 是否访问网络 | 是（API + 浏览器） | 否（本地文件） |
| 与 Pipeline 关系 | 独立服务，不触发 Pipeline | 独立服务，不触发 Pipeline |

Downloader 的职责在"论文下载到本地"处结束。Scanner 从 `shared_workspace/papers/raw/` 开始处理。

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                     Hermes Agent (决策层)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ 读取下载摘要 │  │ 失败项决策   │  │ 生成报告 + checkpoint   │ │
│  │ (API源+浏览器│  │ (重试/跳过/ │  │ downloader_report_*.md │ │
│  │  源汇总)    │  │  调配置)    │  │ .agent_checkpoint.json  │ │
│  └──────┬──────┘  └──────┬──────┘  └─────────────────────────┘ │
│         │                │                                       │
│         └────────────────┘                                       │
│              terminal 调用                                       │
│         ┌────────────────────────────────────────┐               │
│         │  WebBridge (浏览器源: SSRN/AQR/etc.)   │               │
│         │  fetch / download / save_pdf           │               │
│         └────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Paper Downloader Engine (执行层)                    │
│  ┌─────────────┐     ┌─────────────────────┐     ┌───────────┐ │
│  │  Scheduler  │────▶│  Source Plugins     │────▶│  Store    │ │
│  │  按频率调度  │     │  (纯 HTTP/API 源)   │     │ SQLite DB │ │
│  └─────────────┘     └─────────────────────┘     └─────┬─────┘ │
│         │                    │                         │       │
│         │                    ▼                         ▼       │
│         │           ┌──────────────┐          ┌────────────┐  │
│         │           │ arXiv API/GCS│          │ raw/{src}/ │  │
│         │           │ CORE API     │          │   {id}.pdf │  │
│         │           │ Elsevier API │          └────────────┘  │
│         │           │ Wiley TDM    │                  │       │
│         │           │ 会议官网爬取  │                  │       │
│         │           └──────────────┘                  │       │
│         └─────────────────────────────────────────────┘       │
│                        (HTTP 下载)                             │
└─────────────────────────────────────────────────────────────────┘
```

**核心原则**：
- **Python 引擎** = 纯 API/HTTP 源的后台批量下载器（无浏览器交互）
- **Agent** = 负责需要 WebBridge 的浏览器源 + 全局决策 + 报告生成
- 两者共享 `downloads.db` 和 `shared_workspace/papers/raw/` 存储

---

## 3. 组件边界

### 3.1 Python 下载引擎（`tools/paper_downloader/`）

**做什么**：
- 纯 API/HTTP 源的扫描、发现、下载
- SQLite 数据库操作（去重、状态追踪）
- 统一的重试、rate limit、路径生成
- CLI 接口

**不做什么**：
- 不碰浏览器（WebBridge）
- 不做 PDF 解析或内容分析
- 不做方法论审计（那是 Scanner 的事）

### 3.2 Hermes Agent（`agent_configs/paper_downloader/`）

**做什么**：
- 触发引擎执行 API 源扫描
- 用 WebBridge 处理浏览器源（SSRN、AQR 等）
- 读取下载摘要，做失败项决策（重试 / 跳过 / 调配置）
- 生成双语报告 + `.agent_checkpoint.json`

**不做什么**：
- 不写爬虫代码（只调用已测试好的引擎 CLI）
- 不直接处理大量 HTTP 下载（交给引擎）

---

## 4. 目录结构

```
tools/paper_downloader/
├── __init__.py
├── __main__.py              # CLI 入口: python -m paper_downloader
├── config.yaml              # 各源频率/开关/回溯设置
├── core/
│   ├── __init__.py
│   ├── scheduler.py         # 调度器：按频率决定跑哪些源
│   ├── store.py             # SQLite 封装：去重、状态追踪
│   ├── models.py            # PaperMeta, SourceConfig dataclass
│   └── downloader.py        # 统一下载逻辑：重试、rate limit、路径生成
├── sources/
│   ├── __init__.py
│   ├── base.py              # Source 抽象基类
│   ├── arxiv.py             # arXiv API + GCS batch (q-fin + cs.LG)
│   ├── core_ac.py           # CORE API (期刊 OA 全覆盖)
│   ├── elsevier.py          # Elsevier Scopus + Article Retrieval API
│   ├── wiley.py             # Wiley Crossref + TDM API
│   └── conference.py        # NeurIPS/ICML/ICLR/KDD/ICAIF
└── tests/                   # 每个 source 独立单元测试
    ├── test_arxiv.py
    ├── test_core_ac.py
    └── ...

agent_configs/paper_downloader/
├── SOUL.md                  # Agent 系统 prompt + 工作流定义
└── config.yaml              # Hermes 运行时配置（port, model, tools）
```

---

## 5. 数据模型

### 5.1 PaperMeta (`core/models.py`)

```python
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import json

@dataclass
class PaperMeta:
    """一篇论文的元数据，所有 Source 统一输出此格式"""
    source: str              # 来源标识，如 "arxiv_qfin", "core", "ssrn"
    source_id: str           # 来源内部 ID，如 arxiv_id, core_id, ssrn_id
    doi: Optional[str] = None
    title: str = ""
    authors: List[str] = None
    abstract: Optional[str] = None
    published_at: Optional[datetime] = None
    year: Optional[int] = None
    pdf_url: Optional[str] = None   # 直接 PDF 链接
    landing_url: Optional[str] = None  # 文章主页

    def unique_key(self) -> str:
        """去重标识：有 DOI 用 DOI，否则用 source + source_id"""
        return self.doi.lower() if self.doi else f"{self.source}:{self.source_id}"

    def suggested_filename(self) -> str:
        """建议的文件名：{source}_{source_id}.pdf"""
        safe_id = self.source_id.replace("/", "_").replace(":", "_")
        return f"{self.source}_{safe_id}.pdf"
```

### 5.2 Plugin 抽象基类 (`sources/base.py`)

```python
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import List
from core.models import PaperMeta

class Source(ABC):
    """每个来源必须实现的接口"""
    
    name: str = ""           # 来源标识，如 "arxiv_qfin"
    frequency: str = ""      # "daily", "weekly", "monthly", "yearly", "on_demand"
    rate_limit_delay: float = 3.0  # 同一 source 内请求间隔（秒）
    max_retries: int = 3
    
    @abstractmethod
    def scan(self, since: datetime) -> List[PaperMeta]:
        """
        发现自 since 以来发布/更新的论文。
        since 由调度器根据数据库中该 source 最新的 published_at 自动计算。
        首次运行或回溯时，since 可能追溯到 2010-01-01。
        """
        pass
    
    @abstractmethod
    def download(self, meta: PaperMeta, dest_path: Path) -> Path:
        """
        将 PDF 下载到 dest_path，返回最终文件路径。
        下载失败应抛出 DownloadError，由上层统一处理重试。
        """
        pass
```

**关键设计决策**：
- `scan()` 只返回元数据，**不下载 PDF**——把"发现"和"下载"解耦，方便单独测试和失败重试
- `since` 由调度器自动推导，plugin 不用管增量逻辑
- 下载目标路径由调度器生成（`shared_workspace/papers/raw/{source}/{year}/`），plugin 只管写入

---

## 6. 存储设计

### 6.1 SQLite Schema (`core/store.py`)

```sql
-- 主表：所有发现过的论文
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    doi TEXT,
    title TEXT NOT NULL,
    authors TEXT,              -- JSON array
    abstract TEXT,
    published_at TEXT,         -- ISO 8601
    year INTEGER,
    pdf_url TEXT,
    landing_url TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    downloaded_at TEXT,
    filepath TEXT,
    -- 状态机
    status TEXT DEFAULT 'pending' 
        CHECK(status IN ('pending', 'downloaded', 'failed', 'skipped')),
    fail_count INTEGER DEFAULT 0,
    last_fail_reason TEXT,
    UNIQUE(source, source_id)
);

-- DOI 去重索引（只有 DOI 非空时才生效）
CREATE UNIQUE INDEX IF NOT EXISTS idx_doi ON papers(doi) WHERE doi IS NOT NULL;

-- 快速查询索引
CREATE INDEX IF NOT EXISTS idx_source_status ON papers(source, status);
CREATE INDEX IF NOT EXISTS idx_published_at ON papers(published_at);
CREATE INDEX IF NOT EXISTS idx_year ON papers(year);

-- 调度日志：记录每次扫描的摘要（供 Agent 读取）
CREATE TABLE IF NOT EXISTS scan_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT DEFAULT (datetime('now')),
    finished_at TEXT,
    source TEXT NOT NULL,
    found_count INTEGER DEFAULT 0,
    new_count INTEGER DEFAULT 0,      -- 真正新增（去重后）
    downloaded_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running'
        CHECK(status IN ('running', 'success', 'partial_failure', 'failed'))
);
```

### 6.2 存储层核心操作

```python
class PaperStore:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(db_path)
        self._init_schema()
    
    def dedupe_and_insert(self, metas: List[PaperMeta]) -> List[PaperMeta]:
        """批量插入，跳过已存在的（source, source_id）或 DOI 重复项。"""
        pass
    
    def get_pending(self, source: str, limit: int = 100) -> List[PaperMeta]:
        """获取某 source 待下载的论文"""
        pass
    
    def mark_downloaded(self, paper_id: int, filepath: Path):
        pass
    
    def mark_failed(self, paper_id: int, reason: str):
        """fail_count += 1，如果 >= 3 则转为 skipped"""
        pass
    
    def get_scan_summary(self, since: datetime) -> dict:
        """供 Agent 读取最近一轮扫描统计"""
        pass
    
    def get_latest_published_at(self, source: str) -> Optional[datetime]:
        """调度器用：获取某 source 已下载论文的最新 published_at"""
        pass
```

### 6.3 增量与去重逻辑

**去重策略（按优先级）**：

1. **DOI 匹配**：两篇论文 DOI 相同 → 同一篇，后发现的丢弃
2. **(source, source_id) 匹配**：同一来源同一 ID → 同一篇
3. **标题相似度 fallback**（可选）：跨来源比对（如 arXiv preprint 和期刊正式版），用标题编辑距离 > 0.9 判定，标记为 `duplicate_of`

**增量策略**：

```
每次扫描时：
  since = store.get_latest_published_at(source) 
  if since is None:
      since = config.backfill_start_date  -- 首次运行/回溯
  
  metas = source.scan(since)
  new_metas = store.dedupe_and_insert(metas)
  
  for meta in new_metas:
      try:
          filepath = generate_path(meta)  -- raw/{source}/{year}/{filename}.pdf
          source.download(meta, filepath)
          store.mark_downloaded(meta.id, filepath)
      except Exception as e:
          store.mark_failed(meta.id, str(e))
```

---

## 7. 各 Source 接入策略

### 总览表

| Source | 发现机制 | 下载方式 | 频率 | 执行者 | 状态 |
|--------|---------|---------|------|--------|------|
| **arXiv q-fin** | OAI-PMH / API / GCS | `arxiv.org/pdf/{id}` or GCS | 每周 | 引擎 | ✅ 一期 |
| **arXiv cs.LG** | OAI-PMH / API / GCS | `arxiv.org/pdf/{id}` or GCS | 每周 | 引擎 | ✅ 一期 |
| **CORE API** | `/search/works` + `/search/outputs` | `/outputs/{id}/download` | 每月 | 引擎 | ✅ 一期 |
| **Elsevier** | Scopus Search API | Article Retrieval API | 每月 | 引擎 | ✅ 一期 |
| **Wiley** | Crossref API (CC-BY) | TDM API | 每月 | 引擎 | ✅ 一期 |
| **NeurIPS** | 官网 proceedings | PDF 直链 | 每年 | 引擎 | ✅ 一期 |
| **SSRN** | WebBridge fetch | WebBridge download | 每周 | Agent | ⚠️ 一期 |
| ICML | 官网 proceedings | PDF 直链 | 每年 | 引擎 | ⏳ 二期 |
| ICLR | OpenReview API | PDF 直链 | 每年 | 引擎 | ⏳ 二期 |
| KDD | ACM proceedings | PDF 直链 | 每年 | 引擎 | ⏳ 二期 |
| ICAIF | 官网 proceedings | PDF 直链 | 每年 | 引擎 | ⏳ 二期 |
| AQR | WebBridge fetch | WebBridge save_pdf | 每月 | Agent | ⏳ 二期 |
| Oxford-Man | WebBridge fetch | WebBridge save_pdf | 每月 | Agent | ⏳ 二期 |
| Alpha Architect | WebBridge fetch | WebBridge save_pdf | 每月 | Agent | ⏳ 二期 |
| Sci-Hub | DOI 解析 | 镜像站点 | 按需 | Agent | 🔒 预留 |

### 7.1 arXiv (`sources/arxiv.py`)

arXiv 有两种使用模式：**增量更新**（每周扫新论文）和**批量回溯**（首次运行/回填历史）。

#### 增量更新 — OAI-PMH / API

```python
# 方式 A：OAI-PMH（推荐增量，稳定、标准）
BASE = "https://export.arxiv.org/oai2"
# 参数：verb=ListRecords&metadataPrefix=arXivRaw&set=cs.LG&from={since}

# 方式 B：API Search（更灵活，支持排序和过滤）
BASE = "http://export.arxiv.org/api/query"
# 参数：search_query=cat:q-fin.TR&sortBy=submittedDate&sortOrder=descending&start=0&max_results=100
```

arXiv 的 `set` / `cat` 参数支持分类：
- `q-fin.TR` (Trading and Market Microstructure)
- `q-fin.PM` (Portfolio Management)
- `q-fin.MF` (Mathematical Finance)
- `q-fin.CP` (Computational Finance)
- `q-fin.ST` (Statistical Finance)
- `cs.LG` (Machine Learning)
- `cs.AI` (Artificial Intelligence)

#### 批量回溯 — GCS 公开 Bucket（Kaggle 数据集）

arXiv 与 Kaggle 合作提供完整的机器可读数据集，PDF 存储在 **公开 GCS bucket** 中：

```python
# GCS bucket 公开可访问，无需认证
GCS_BASE = "https://storage.googleapis.com/arxiv-dataset"

# PDF 路径格式（现代编号，2007 年后）
pdf_url = f"{GCS_BASE}/arxiv/arxiv/pdf/{YYMM}/{arxiv_id}v{version}.pdf"
# 例：https://storage.googleapis.com/arxiv-dataset/arxiv/arxiv/pdf/2401/2401.00001v1.pdf

# 旧格式（按分类目录）
pdf_url = f"{GCS_BASE}/arxiv/{category}/pdf/{YYMM}/{arxiv_id}v{version}.pdf"
# 例：https://storage.googleapis.com/arxiv-dataset/arxiv/q-fin/pdf/2401/2401.12345v1.pdf
```

**批量下载策略**：
```python
import requests
import xml.etree.ElementTree as ET

def list_gcs_pdfs(prefix: str) -> list:
    """用 GCS XML API 列出指定前缀下的所有 PDF"""
    url = f"https://storage.googleapis.com/arxiv-dataset?prefix={prefix}&max-keys=1000"
    resp = requests.get(url)
    root = ET.fromstring(resp.content)
    ns = {'s3': 'http://doc.s3.amazonaws.com/2006-03-01'}
    keys = [k.text for k in root.findall('.//s3:Key', ns) if k.text.endswith('.pdf')]
    return keys

# 示例：列出 2024 年 1 月所有 q-fin PDF
# keys = list_gcs_pdfs("arxiv/arxiv/pdf/2401/")
# 然后多线程批量下载（GCS 无 rate limit）
```

**Metadata 获取**：
- GCS bucket 中**不含** metadata JSON
- 5.31 GB 的 `arxiv-metadata-oai-snapshot.json` 需从 Kaggle 下载
- 或者：先用 OAI-PMH/API 获取目标论文列表，再从 GCS 批量下载对应 PDF

#### 下载方式对比

| 场景 | 推荐方式 | URL | Rate Limit |
|------|---------|-----|------------|
| 增量（每周） | arxiv.org | `https://arxiv.org/pdf/{id}.pdf` | 建议 1-3s（礼貌） |
| 回溯（批量） | GCS 直链 | `https://storage.googleapis.com/arxiv-dataset/arxiv/arxiv/pdf/{YYMM}/{id}v{v}.pdf` | **无限制** |
| Source tarball | arxiv.org | `https://arxiv.org/e-print/{id}` | 建议 1-3s |

**注意**：
- arXiv 论文通常**没有 DOI**（预印本），去重靠 `(source, source_id)`
- GCS 上的 PDF 文件名包含版本号（如 `2401.00001v1.pdf`），不带版本号的 URL 返回 404
- `arxiv.org/pdf/{id}.pdf` 会 301 重定向到无 `.pdf` 后缀的 URL，但 Content-Type 仍为 PDF

### 7.2 CORE API (`sources/core_ac.py`)

CORE API v3 有两类实体：
- **Works**：去重后的统一元实体，用于搜索发现和获取合并元数据
- **Outputs**：原始采集记录，用于下载 PDF（保留原始 `downloadUrl`）

**发现（搜索 Works）**：
```python
# 端点：GET https://api.core.ac.uk/v3/search/works
headers = {"Authorization": f"Bearer {CORE_API_KEY}"}
params = {
    "q": f'(title:"Journal of Finance" OR title:"Journal of Financial Economics" '
           f'OR title:"Review of Financial Studies" OR title:"Review of Finance") '
           f'AND yearPublished>={since_year} AND _exists_:fullText',
    "limit": 100,       # 最大 100
    "offset": offset,
    "sort": "recency",  # relevance | recency
}
# 注意：使用 GET + query string，不是 POST + body
```

**查询语法（field lookup）**：
| 语法 | 示例 | 说明 |
|------|------|------|
| `title:"..."` | `title:"machine learning"` | 标题精确短语 |
| `yearPublished>2020` | `yearPublished>="2015"` | 年份范围 |
| `_exists_:fullText` | `_exists_:downloadUrl` | 字段存在性 |
| AND / OR | `(A OR B) AND C` | 逻辑组合 |
| `authors:"..."` | `authors:Smith` | 作者搜索 |
| `doi:"..."` | `doi:"10.1007/..."` | DOI 精确匹配 |

**期刊元数据**：Works/Outputs 的 `journals` 字段包含期刊标题和 ISSN：
```json
"journals": [{"title": "Journal of Financial Economics", "identifiers": ["issn:0304-405X"]}]
```
注意：`journals` 字段**不支持字段查找搜索**，但自由文本搜索可命中。

**下载流程**：
```python
# Step 1: 用 Work ID 获取关联的 Outputs
outputs = requests.get(f"https://api.core.ac.uk/v3/works/{work_id}/outputs", headers=headers).json()

# Step 2: 从第一个 Output 取 downloadUrl（官方推荐首选方式）
pdf_url = outputs["results"][0]["downloadUrl"]  # 原始 PDF 直链

# Step 3: fallback — CORE 下载端点
# GET https://api.core.ac.uk/v3/outputs/{output_id}/download → 返回 PDF
# 注意：/v3/works/{id}/download 返回 TEI 文件，不是 PDF！
```

**速率限制**：25 req/min。响应头：`x-ratelimit-limit`, `x-ratelimit-remaining`, `x-ratelimit-retry-after`。

### 7.3 Elsevier (`sources/elsevier.py`)

**发现（Scopus Search API）**：
```python
# 免费 API key 可用 Scopus Search，ScienceDirect Search 需机构授权
URL = "https://api.elsevier.com/content/search/scopus"
params = {
    "query": f'SRCTITLE("Journal of Financial Economics") AND openaccess(1) AND PUBYEAR > {since_year}',
    "count": 25,      # Scopus 推荐 25
    "start": offset,
    "sort": "-pubyear",  # 按出版年倒序
}
headers = {"X-ELS-APIKey": ELSEVIER_API_KEY}
```

- `SRCTITLE("...")` 精确限定期刊，`openaccess(1)` 只返回 OA
- 同样支持 `Journal of Banking & Finance`, `Journal of Empirical Finance` 等
- 返回含 DOI, title, authors, publicationDate, eid

**下载（Article Retrieval API）**：
```python
url = f"https://api.elsevier.com/content/article/doi/{doi}?httpAccept=application/pdf"
headers = {"X-ELS-APIKey": ELSEVIER_API_KEY}
resp = requests.get(url, headers=headers)

if resp.status_code == 200:
    # 检查是否是完整 PDF（非 1-page limited）
    status = resp.headers.get("x-els-status", "")
    if "not entitled" in status or "WARNING" in status:
        # 非 OA：返回 1-page 预览，标记 paywalled
        mark_paywalled(doi)
    else:
        save_pdf(resp.content)
elif resp.status_code == 403:
    mark_paywalled(doi)
```

**注意**：
- 免费 key 可用 Scopus Search，但 `search/sciencedirect` 需机构授权
- OA 检测需同时检查 status code 和 `x-els-status` header（非 OA 可能返回 200 + 1-page PDF + WARNING header）

### 7.4 Wiley (`sources/wiley.py`)

**发现（Crossref API，Wiley RSS 已废弃）**：
```python
# 通过 Crossref 过滤 Wiley 出版的 CC-BY 文章
URL = "https://api.crossref.org/works"
params = {
    "filter": f"publisher-name:Wiley,from-pub-date:{since_year}-01-01,license.url:http://creativecommons.org/licenses/by",
    "query.title": "Journal of Finance OR \"Review of Financial Studies\"",
    "rows": 100,
    "offset": offset,
    "sort": "published",
    "order": "desc",
}
```

- Crossref 的 `license.url` 过滤可精确筛选 OA 文章
- 返回含 DOI, title, authors, published-print/online date
- 需配合 `publisher-name:Wiley` 限定出版社

**下载（Wiley TDM API）**：
```python
url = f"https://api.wiley.com/onlinelibrary/tdm/v1/articles/{doi}"
headers = {"Wiley-TDM-Client-Token": WILEY_TDM_TOKEN}
resp = requests.get(url, headers=headers, allow_redirects=True)

if resp.status_code == 200 and len(resp.content) > 10000:
    # TDM API 会 302 重定向到实际 PDF 地址，跟随后 200 = OA
    save_pdf(resp.content)
elif resp.status_code == 403:
    # 非 OA：TDM 拒绝访问
    mark_paywalled(doi)
```

**注意**：
- Wiley RSS feed 已停止维护，不可用
- TDM API 仅对 OA 文章有效，非 OA 返回 403
- 需注册获取 `Wiley-TDM-Client-Token`（免费）

### 7.5 会议论文 (`sources/conference.py`)

所有 ML/AI 会议的 proceedings 结构高度相似，可以做一个基类 + 各会议子类。

**NeurIPS（示例）**：
```
发现：
  1. 访问 https://papers.nips.cc/paper/{year}
  2. 解析 HTML 获取所有论文标题和详情页链接
  3. 访问每篇论文详情页提取 authors, abstract, PDF 链接

下载：
  PDF 直链在详情页中，如 https://papers.nips.cc/paper/2024/file/xxxx.pdf
```

**ICML**：`https://proceedings.mlr.press/v{volume}/`（PMLR 托管）

**ICLR**：`https://openreview.net/group?id=ICLR.cc/{year}/Conference`（OpenReview API）

**KDD**：`https://dl.acm.org/doi/proceedings/10.1145/xxxx`（ACM Digital Library，OA 部分有限）

**ICAIF**：`https://ai-finance.org/icaif-{year}-proceedings/`（因年份而异）

**策略**：
- 会议 proceedings 是**年度一次性事件**，频率设为 `yearly`
- 每年会议结束后手动/Agent 触发一次批量抓取
- 不是持续监控源，而是"发布后一次性收割"

### 7.6 SSRN（Agent 执行）

**重要发现**：SSRN 虽被 Elsevier 收购，但其内容**未整合**进 Elsevier API：
- Elsevier Article Retrieval API → 404 `RESOURCE_NOT_FOUND`
- Scopus Search API → 0 results
- 必须通过浏览器直接访问 SSRN 网站

**难点**：
- 没有公开 API
- Cloudflare 反爬严格（`cf-mitigated: challenge`），curl 直接访问返回 403
- 必须使用真实浏览器（WebBridge）

**发现（Agent 通过 WebBridge）**：
```bash
# Agent 用 WebBridge fetch SSRN 搜索页
python3 tools/webbridge_client.py fetch \
  --url "https://www.ssrn.com/index.cfm/en/" \
  --session downloader-ssrn
```
Agent 解析返回的 snapshot 提取论文列表（title, authors, URL, SSRN ID）。

**页面结构**：
- 论文页：`https://papers.ssrn.com/sol3/papers.cfm?abstract_id={id}`
- 页面含 cookie consent banner（OneTrust），需处理后才能交互
- PDF 下载按钮：动态 URL，必须从 abstract 页面提取（含 UUID/token，不可硬编码）

**下载（Agent 通过 WebBridge）**：
```bash
# 方式 A：直接构造 PDF URL（无需登录，已验证可用）
# PDF URL contains a dynamic UUID/token — must extract from abstract page
# Example: Delivery.cfm/SSRN_ID4501707_code759326.pdf?abstractid=4501707&mirid=1
# Agent workflow: visit abstract page → find "Download This Paper" link → extract href

# 方式 B：从论文页点击下载按钮
python3 tools/webbridge_client.py download \
  --url <pdf_url> \
  --session downloader-ssrn
# 返回 base64，Agent 解码保存到 raw/ssrn/
```

**注意**：
- SSRN 论文通常**没有 DOI**，去重靠 `ssrn_id`（即 abstract 编号）
- 下载**无需登录**（至少 OA 论文如此，已验证）
- Agent 处理流程：fetch 列表页 → 解析提取 abstract_id → 直接构造 PDF URL → download

### 7.7 机构简报（二期，Agent 执行）

| 机构 | 发现 URL | 模式 |
|------|---------|------|
| **AQR** | aqr.com/insights-research | 文章列表页，每篇有 PDF/HTML |
| **Oxford-Man** | oxford-man.ox.ac.uk/publications | 学术论文 + working papers |
| **Alpha Architect** | alphaarchitect.com/research | 博客式文章，部分有 PDF |

**策略**：Agent 用 WebBridge `fetch` 列表页 → 解析 snapshot → 提取新文章 → `download` 或 `save_pdf` 获取 PDF。

---

## 8. Rate Limit 设计

**核心原则**：跨源并发、单源限速。

```python
class Source(ABC):
    name: str = ""
    frequency: str = ""
    rate_limit_delay: float = 3.0   # 同一 source 内请求间隔（秒）
    max_retries: int = 3

# 调度器并发逻辑
async def run_all(sources: List[Source]):
    # 不同 source 之间并发执行
    await asyncio.gather(*[run_single(s) for s in sources])

async def run_single(source: Source):
    metas = source.scan(since)
    for meta in metas:
        await download_with_rate_limit(source, meta)
        await asyncio.sleep(source.rate_limit_delay)  # 单源限速
```

**各源建议限速**：

| Source | 建议 delay | 说明 |
|--------|-----------|------|
| arXiv (增量) | 3.0s | 官网 OAI-PMH/API，礼貌限速 |
| arXiv (回溯) | 0.1s | GCS 批量，实测无硬性限制 |
| CORE | 2.4s | 25 req/min |
| Elsevier | 0.5s | ~2 req/sec |
| Wiley | 0.35s | ~3 req/sec |
| 会议网站 | 2.0s | 避免被封 |
| SSRN (Agent) | 5.0s | 模拟浏览器，保守 |

**重试策略**：
- 网络错误（timeout, connection reset）：指数退避 `delay * 2^attempt`，最多 `max_retries`
- Rate limit 429：读取 `Retry-After` header，或 fallback 到 `delay * 5`
- 403 Forbidden（订阅内容）：立即放弃，不重试
- 404 Not Found：立即放弃

---

## 9. Agent 工作流

```markdown
## 工作流

### Phase 1: API 源扫描（引擎执行）
Agent 调用引擎处理所有纯 HTTP 源：
```bash
python3 -m paper_downloader scan --layer api --report
```
引擎返回 JSON 摘要：
```json
{
  "run_id": "2026-05-31-001",
  "started_at": "2026-05-31T08:00:00Z",
  "sources": [
    {"name": "arxiv_qfin", "found": 12, "new": 8, "downloaded": 8, "failed": 0},
    {"name": "arxiv_cslg", "found": 45, "new": 32, "downloaded": 30, "failed": 2},
    {"name": "core_ac", "found": 3, "new": 2, "downloaded": 1, "failed": 1}
  ],
  "total_new": 42,
  "total_downloaded": 39,
  "total_failed": 3
}
```

### Phase 2: 浏览器源扫描（Agent 执行）
Agent 直接用 WebBridge 处理需要浏览器的源（SSRN 等）：

**SSRN**：
1. `webbridge_client.py fetch --url "https://www.ssrn.com/..." --session downloader-ssrn`
2. 解析 snapshot 提取论文列表
3. `webbridge_client.py download --url <pdf_url> --session downloader-ssrn`
4. base64 解码保存到 `shared_workspace/papers/raw/ssrn/`
5. 将元数据写入 `downloads.db`

### Phase 3: 失败项决策
读取 `downloads.db` 中 `status='failed'` 的详细记录：
- fail_count < 3 且原因是网络/限流 → **决策：重试**
- fail_count >= 3 或原因是 403/404 → **决策：跳过**
- 某 source 失败率 > 30% → **决策：标记为 degraded，调整频率或关闭**

执行重试：
```bash
python3 -m paper_downloader retry --run-id 2026-05-31-001
```

### Phase 4: 报告生成
产出：
- `downloader_report_2026-05-31.md`（中文）
- `downloader_report_2026-05-31_en.md`（英文）
- `.agent_checkpoint.json`

报告内容：
- 各源新增/下载/失败统计（含引擎源和 Agent 处理的浏览器源）
- 失败项清单及决策理由
- 下周扫描计划建议
```

---

## 10. CLI 接口设计

```bash
# 扫描指定 sources（不指定则扫全部 enabled）
python3 -m paper_downloader scan [--sources SOURCE1,SOURCE2] [--since YYYY-MM-DD] [--report]

# 只扫描 API 层（引擎源）
python3 -m paper_downloader scan --layer api [--report]

# 重试某次运行中的失败项
python3 -m paper_downloader retry --run-id <id>

# 手动触发单个 source（用于测试新 plugin）
python3 -m paper_downloader test-source --source <name> [--limit 10]

# 查看下载统计
python3 -m paper_downloader stats [--source <name>] [--since YYYY-MM-DD]

# 初始化数据库
python3 -m paper_downloader init-db

# 回填历史（期刊回溯）
python3 -m paper_downloader backfill --source core_ac --year-from 2010 --year-to 2020
```

---

## 11. 配置管理

### 11.1 引擎配置 (`tools/paper_downloader/config.yaml`)

```yaml
# 存储设置
storage:
  raw_dir: "shared_workspace/papers/raw"
  db_path: "shared_workspace/papers/downloads.db"

# 回溯设置
backfill:
  journals_since: "2010-01-01"   # 期刊回溯起始年
  conferences_since: "2020-01-01" # 会议回溯起始年

# API Keys（从环境变量读取，不在配置里写死）
api_keys:
  core_ac: "${CORE_API_KEY}"
  elsevier: "${ELSEVIER_API_KEY}"      # 免费注册，dev.elsevier.com
  wiley_tdm: "${WILEY_TDM_TOKEN}"      # Wiley TDM API token，免费注册

# 各源配置
sources:
  arxiv_qfin:
    enabled: true
    frequency: weekly
    categories: ["q-fin.TR", "q-fin.PM", "q-fin.MF", "q-fin.CP", "q-fin.ST"]
    rate_limit_delay: 3.0
    # GCS 批量回溯配置（首次运行/回填时启用）
    backfill:
      enabled: true
      mode: gcs                    # gcs | api
      gcs_bucket: arxiv-dataset
      year_from: 2010
      year_to: 2024
      rate_limit_delay: 0.1       # GCS 无限制，可快速批量下载
    
  arxiv_cslg:
    enabled: true
    frequency: weekly
    categories: ["cs.LG", "cs.AI"]
    rate_limit_delay: 3.0
    backfill:
      enabled: true
      mode: gcs
      gcs_bucket: arxiv-dataset
      year_from: 2010
      year_to: 2024
      rate_limit_delay: 0.1
    
  core_ac:
    enabled: true
    frequency: monthly
    # 使用 CORE 字段查找语法，非自由文本
    queries:
      - 'title:"Journal of Finance" OR title:"Journal of Financial Economics" OR title:"Review of Financial Studies" OR title:"Review of Finance"'
    year_from: 2010
    rate_limit_delay: 2.4   # 25 req/min
    
  elsevier:
    enabled: true
    frequency: monthly
    journals: ["Journal of Financial Economics", "Journal of Banking & Finance", "Journal of Empirical Finance"]
    year_from: 2010
    rate_limit_delay: 0.5
    
  wiley:
    enabled: true
    frequency: monthly
    # 通过 Crossref 发现，TDM API 下载
    journals: ["Journal of Finance", "Review of Financial Studies"]
    crossref_filter: "publisher-name:Wiley,license.url:http://creativecommons.org/licenses/by"
    year_from: 2010
    rate_limit_delay: 0.35
    
  neurips:
    enabled: true
    frequency: yearly
    rate_limit_delay: 2.0
    
  # 二期源
  ssrn: {enabled: false, frequency: weekly, rate_limit_delay: 5.0}
  icml: {enabled: false, frequency: yearly}
  iclr: {enabled: false, frequency: yearly}
  kdd: {enabled: false, frequency: yearly}
  icaif: {enabled: false, frequency: yearly}
  aqr: {enabled: false, frequency: monthly}
  oxford_man: {enabled: false, frequency: monthly}
  alpha_architect: {enabled: false, frequency: monthly}
  scihub: {enabled: false, frequency: on_demand}
```

### 11.2 Agent 配置 (`agent_configs/paper_downloader/config.yaml`)

```yaml
model: claude-sonnet-4-20250514
api_server:
  port: 8647
  api_key: "sk-downloader-local"
tools:
  enabled: [terminal, file, memory]
terminal:
  allowed_commands: [python3, ls, cat, mkdir, curl]
  timeout: 1800
memory:
  enabled: true
```

---

## 12. 与现有架构集成

### 12.1 Orchestrator DAG 集成

```python
# orchestrator/core/dag.py
AGENTS = {
    # ... 现有 agents ...
    "paper_downloader": {
        "port": 8647,
        "api_key": "sk-downloader-local",
        "workspace": "papers",
    },
}

# 不加入线性 DAG，作为独立定时服务
# EXECUTION_ORDER 保持不变
```

### 12.2 定时触发

```bash
# 方式 A：系统 cron（推荐）
0 8 * * 1 cd /workspace && python3 -m paper_downloader scan --report
# 每周一早 8 点执行

# 方式 B：Agent 内部定时（如果 Hermes 支持）
# 在 config.yaml 中配置 schedule
```

### 12.3 与 Paper Scanner 衔接

```
Downloader 产出: shared_workspace/papers/raw/
Scanner 输入:     shared_workspace/papers/raw/

Scanner 扫描 raw/ 目录时：
  1. 读取 downloads.db 获取元数据（避免重复解析 PDF）
  2. 处理 PDF → 生成卡片 → 写入 papers/{doc_id}/
```

---

## 13. 一期 / 二期范围

### 一期（MVP）

| 模块 | 内容 |
|------|------|
| 引擎核心 | scheduler, store, models, downloader |
| 引擎 Source | arXiv (q-fin + cs.LG), CORE API, Elsevier, Wiley, NeurIPS |
| Agent Source | SSRN（WebBridge） |
| CLI | scan, retry, test-source, stats, init-db, backfill |
| Agent | SOUL.md, config.yaml, 报告生成 |

### 二期

| 模块 | 内容 |
|------|------|
| 引擎 Source | ICML, ICLR, KDD, ICAIF |
| Agent Source | AQR, Oxford-Man, Alpha Architect |
| 引擎增强 | 标题相似度去重、Sci-Hub fallback 插件 |
| 配置 | Web UI 或 CLI 交互式配置管理 |

---

## 14. 文件清单

| 路径 | 类型 | 说明 |
|------|------|------|
| `tools/paper_downloader/` | 新建目录 | 下载引擎 |
| `tools/paper_downloader/__main__.py` | 新建 | CLI 入口 |
| `tools/paper_downloader/config.yaml` | 新建 | 引擎配置 |
| `tools/paper_downloader/core/` | 新建目录 | 核心模块 |
| `tools/paper_downloader/core/models.py` | 新建 | 数据模型 |
| `tools/paper_downloader/core/store.py` | 新建 | SQLite 存储 |
| `tools/paper_downloader/core/scheduler.py` | 新建 | 调度器 |
| `tools/paper_downloader/core/downloader.py` | 新建 | 统一下载逻辑 |
| `tools/paper_downloader/sources/` | 新建目录 | Source plugins |
| `tools/paper_downloader/sources/base.py` | 新建 | 抽象基类 |
| `tools/paper_downloader/sources/arxiv.py` | 新建 | arXiv source |
| `tools/paper_downloader/sources/core_ac.py` | 新建 | CORE source |
| `tools/paper_downloader/sources/elsevier.py` | 新建 | Elsevier source |
| `tools/paper_downloader/sources/wiley.py` | 新建 | Wiley source |
| `tools/paper_downloader/sources/conference.py` | 新建 | 会议 source |
| `tools/paper_downloader/tests/` | 新建目录 | 单元测试 |
| `agent_configs/paper_downloader/SOUL.md` | 新建 | Agent 系统 prompt |
| `agent_configs/paper_downloader/config.yaml` | 新建 | Agent Hermes 配置 |
| `orchestrator/core/dag.py` | 修改 | 新增 Agent 端口定义 |
| `shared_workspace/papers/downloads.db` | 新建 | SQLite 数据库 |
| `shared_workspace/papers/raw/` | 新建目录 | 原始 PDF 存储 |

---

*设计日期：2026-05-31*
*配套设计：[Paper Scanner Agent 设计规格](2026-05-28-paper-scanner-design.md)*
*状态：待审查*
