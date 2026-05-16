"""HTML Reporter — generate a beautified interactive report from pipeline artifacts."""
import json
import base64
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

try:
    import markdown
    _HAS_MARKDOWN = True
except ImportError:
    _HAS_MARKDOWN = False

# ── Template ───────────────────────────────────────────────────────
_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Quant Report — {{ topic }}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
:root {
  --bg: #0d1117; --bg-elevated: #161b22; --bg-card: #1c2128;
  --border: #30363d; --text: #c9d1d9; --text-muted: #8b949e;
  --accent: #58a6ff; --accent-green: #3fb950; --accent-red: #f85149;
  --accent-yellow: #d29922; --accent-orange: #db6d28;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.6;
}
/* Dashboard */
.dashboard {
  background: linear-gradient(135deg, #1c2128 0%, #0d1117 100%);
  border-bottom: 1px solid var(--border);
  padding: 32px 40px;
}
.dashboard h1 { font-size: 28px; margin-bottom: 8px; }
.dashboard .meta { color: var(--text-muted); font-size: 13px; margin-bottom: 20px; }
.metrics-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 16px; max-width: 900px;
}
.metric-card {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: 10px; padding: 16px; text-align: center;
}
.metric-card .value { font-size: 26px; font-weight: 700; }
.metric-card .label { font-size: 12px; color: var(--text-muted); margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
.metric-card.up .value { color: var(--accent-green); }
.metric-card.down .value { color: var(--accent-red); }
.metric-card.warn .value { color: var(--accent-yellow); }

/* Layout */
.container { display: flex; min-height: calc(100vh - 200px); }
.sidebar {
  width: 220px; background: var(--bg-elevated);
  border-right: 1px solid var(--border); padding: 20px 0;
  position: sticky; top: 0; height: 100vh; overflow-y: auto;
}
.sidebar a {
  display: block; padding: 10px 24px; color: var(--text-muted);
  text-decoration: none; font-size: 14px; border-left: 3px solid transparent;
}
.sidebar a:hover, .sidebar a.active { color: var(--text); background: rgba(88,166,255,0.08); border-left-color: var(--accent); }
.sidebar .nav-title { padding: 16px 24px 8px; font-size: 11px; text-transform: uppercase; color: var(--text-muted); letter-spacing: 1px; }

/* Content */
.content { flex: 1; padding: 32px 40px; max-width: 1000px; }
.stage-section { margin-bottom: 48px; }
.stage-header {
  display: flex; align-items: center; gap: 12px; margin-bottom: 24px;
  padding-bottom: 12px; border-bottom: 1px solid var(--border);
}
.stage-header h2 { font-size: 22px; }
.stage-badge {
  font-size: 11px; padding: 3px 10px; border-radius: 20px;
  background: var(--bg-card); border: 1px solid var(--border); color: var(--text-muted);
}

/* Markdown content */
.md-content h1, .md-content h2, .md-content h3 { margin: 24px 0 12px; }
.md-content h1 { font-size: 20px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
.md-content h2 { font-size: 17px; color: var(--accent); }
.md-content h3 { font-size: 15px; }
.md-content p { margin: 10px 0; color: var(--text-muted); }
.md-content ul, .md-content ol { margin: 10px 0 10px 24px; color: var(--text-muted); }
.md-content li { margin: 4px 0; }
.md-content code {
  background: var(--bg-elevated); padding: 2px 6px; border-radius: 4px;
  font-family: "SF Mono", Monaco, monospace; font-size: 13px;
}
.md-content pre {
  background: var(--bg-elevated); padding: 16px; border-radius: 8px;
  overflow-x: auto; border: 1px solid var(--border);
}
.md-content blockquote {
  border-left: 3px solid var(--accent); padding-left: 16px; margin: 16px 0;
  color: var(--text-muted); font-style: italic;
}
.md-content table {
  width: 100%; border-collapse: collapse; margin: 16px 0;
  font-size: 13px;
}
.md-content th, .md-content td {
  padding: 10px 12px; text-align: left; border: 1px solid var(--border);
}
.md-content th { background: var(--bg-elevated); font-weight: 600; }
.md-content tr:nth-child(even) { background: rgba(255,255,255,0.02); }

/* Images */
.report-image {
  max-width: 100%; border-radius: 8px; border: 1px solid var(--border);
  margin: 16px 0;
}
.image-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 16px; margin: 16px 0;
}
.image-grid img { width: 100%; }

/* Lang tabs */
.lang-tabs { display: flex; gap: 4px; margin-bottom: 16px; }
.lang-tab {
  padding: 6px 16px; border-radius: 6px; cursor: pointer;
  font-size: 13px; background: var(--bg-elevated); border: 1px solid var(--border);
  color: var(--text-muted);
}
.lang-tab.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.lang-panel { display: none; }
.lang-panel.active { display: block; }

/* Footer */
.footer { text-align: center; padding: 40px; color: var(--text-muted); font-size: 12px; border-top: 1px solid var(--border); }

/* Scroll */
html { scroll-behavior: smooth; }
</style>
</head>
<body>

<!-- Dashboard -->
<div class="dashboard">
  <h1>🎯 {{ topic }}</h1>
  <div class="meta">
    Run ID: <code style="background:var(--bg-card);padding:2px 8px;border-radius:4px;">{{ run_id }}</code>
    &nbsp;·&nbsp; Completed: {{ completed_at }}
    &nbsp;·&nbsp; {{ stage_count }} Stages
  </div>
  <div class="metrics-grid">
    {% for m in metrics %}
    <div class="metric-card {{ m.css_class }}">
      <div class="value">{{ m.value }}</div>
      <div class="label">{{ m.label }}</div>
    </div>
    {% endfor %}
  </div>
</div>

<div class="container">
  <!-- Sidebar -->
  <nav class="sidebar">
    <div class="nav-title">Pipeline</div>
    {% for stage in stages %}
    <a href="#{{ stage.id }}" {% if loop.first %}class="active"{% endif %}>{{ stage.name }}</a>
    {% endfor %}
    <div class="nav-title">Charts</div>
    {% for chart in all_charts %}
    <a href="#chart-{{ loop.index }}">{{ chart.title }}</a>
    {% endfor %}
  </nav>

  <!-- Content -->
  <main class="content">
    {% for stage in stages %}
    <section class="stage-section" id="{{ stage.id }}">
      <div class="stage-header">
        <h2>{{ stage.emoji }} {{ stage.name }}</h2>
        <span class="stage-badge">{{ stage.file_count }} files</span>
      </div>

      {% if stage.has_bilingual %}
      <div class="lang-tabs">
        <div class="lang-tab active" onclick="switchLang(this,'{{ stage.id }}','zh')">🇨🇳 中文</div>
        <div class="lang-tab" onclick="switchLang(this,'{{ stage.id }}','en')">🇺🇸 English</div>
      </div>
      <div class="lang-panel active" id="panel-{{ stage.id }}-zh">
        <div class="md-content">{{ stage.content_zh | safe }}</div>
      </div>
      <div class="lang-panel" id="panel-{{ stage.id }}-en">
        <div class="md-content">{{ stage.content_en | safe }}</div>
      </div>
      {% else %}
      <div class="md-content">{{ stage.content | safe }}</div>
      {% endif %}

      {% if stage.charts %}
      <div class="image-grid">
        {% for chart in stage.charts %}
        <div id="chart-{{ chart.global_idx }}">
          <img src="{{ chart.src }}" alt="{{ chart.name }}" class="report-image">
        </div>
        {% endfor %}
      </div>
      {% endif %}
    </section>
    {% endfor %}

    <div class="footer">
      Generated by Quant Cluster · {{ completed_at }}
    </div>
  </main>
</div>

<script>
function switchLang(tab, stageId, lang) {
  const parent = tab.parentElement;
  parent.querySelectorAll('.lang-tab').forEach(t => t.classList.remove('active'));
  tab.classList.add('active');
  document.querySelectorAll(`#panel-${stageId}-zh, #panel-${stageId}-en`).forEach(p => p.classList.remove('active'));
  document.getElementById(`panel-${stageId}-${lang}`).classList.add('active');
}
// Highlight active nav on scroll
const sections = document.querySelectorAll('.stage-section');
const navLinks = document.querySelectorAll('.sidebar a[href^="#"]');
window.addEventListener('scroll', () => {
  let current = '';
  sections.forEach(sec => {
    const rect = sec.getBoundingClientRect();
    if (rect.top <= 200) current = sec.id;
  });
  navLinks.forEach(link => {
    link.classList.toggle('active', link.getAttribute('href') === '#' + current);
  });
});
</script>

</body>
</html>
"""


def _md_to_html(text: str) -> str:
    """Convert markdown to HTML."""
    if _HAS_MARKDOWN:
        return markdown.markdown(
            text,
            extensions=["tables", "fenced_code", "toc"],
            extension_configs={"toc": {"permalink": False}},
        )
    # Fallback: very basic conversion
    lines = text.splitlines()
    out = []
    in_code = False
    for line in lines:
        if line.startswith("```"):
            if not in_code:
                out.append("<pre><code>")
                in_code = True
            else:
                out.append("</code></pre>")
                in_code = False
            continue
        if in_code:
            out.append(line)
            continue
        if line.startswith("# "):
            out.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("- "):
            out.append(f"<li>{line[2:]}</li>")
        elif line.strip() == "":
            out.append("<br>")
        else:
            out.append(f"<p>{line}</p>")
    return "\n".join(out)


def _extract_metrics(archive_dir: Path) -> List[Dict[str, Any]]:
    """Extract key metrics from JSON artifacts for the dashboard."""
    metrics = []

    # Try audit_summary.json
    audit_summary = archive_dir / "04_risk" / "audit_summary.json"
    if audit_summary.exists():
        try:
            data = json.loads(audit_summary.read_text())
            # PBO — try multiple field names
            pbo = data.get("cscv_pbo_4strat") or data.get("cscv_pbo_2strat") or data.get("pbo")
            if isinstance(pbo, (int, float)):
                cls = "up" if pbo < 0.3 else "warn" if pbo < 0.5 else "down"
                metrics.append({"label": "PBO", "value": f"{pbo:.2f}", "css_class": cls})
            # Sharpe — try multiple field names
            sharpe = (data.get("walkforward_mean_oos_sharpe") or data.get("oos_sharpe_mean")
                      or data.get("observed_sharpe") or data.get("sharpe"))
            if isinstance(sharpe, (int, float)):
                cls = "up" if sharpe > 1.0 else "warn" if sharpe > 0 else "down"
                metrics.append({"label": "Sharpe", "value": f"{sharpe:.2f}", "css_class": cls})
            # Max Drawdown — try multiple field names
            dd = (data.get("max_dd_baseline_chrono") or data.get("max_dd_regime_chrono")
                  or data.get("overall_max_drawdown") or data.get("max_drawdown"))
            if isinstance(dd, (int, float)):
                cls = "down" if dd < -0.2 else "warn"
                metrics.append({"label": "Max Drawdown", "value": f"{dd*100:.1f}%", "css_class": cls})
        except Exception:
            pass

    # Try audit_computed.json as fallback
    audit_computed = archive_dir / "04_risk" / "audit_computed.json"
    if audit_computed.exists() and not any(m["label"] == "PBO" for m in metrics):
        try:
            data = json.loads(audit_computed.read_text())
            pbo = data.get("cscv_pbo_proxy") or data.get("pbo")
            if isinstance(pbo, (int, float)):
                cls = "up" if pbo < 0.3 else "warn" if pbo < 0.5 else "down"
                metrics.append({"label": "PBO", "value": f"{pbo:.2f}", "css_class": cls})
            sharpe = data.get("observed_sharpe") or data.get("oos_sharpe_mean")
            if isinstance(sharpe, (int, float)) and not any(m["label"] == "Sharpe" for m in metrics):
                cls = "up" if sharpe > 1.0 else "warn" if sharpe > 0 else "down"
                metrics.append({"label": "Sharpe", "value": f"{sharpe:.2f}", "css_class": cls})
            dd = data.get("overall_max_drawdown") or data.get("max_drawdown")
            if isinstance(dd, (int, float)) and not any(m["label"] == "Max Drawdown" for m in metrics):
                cls = "down" if dd < -0.2 else "warn"
                metrics.append({"label": "Max Drawdown", "value": f"{dd*100:.1f}%", "css_class": cls})
        except Exception:
            pass

    # Try backtest results
    backtest_dir = archive_dir / "03_backtest"
    for bt_file in backtest_dir.glob("backtest_results_*.json"):
        try:
            data = json.loads(bt_file.read_text())
            if not isinstance(data, dict):
                continue
            # Skip tiny baseline files (they're just split metadata)
            if bt_file.stat().st_size < 1000:
                continue
            if "total_return" in data:
                val = data["total_return"]
                metrics.append({"label": "Total Return", "value": f"{val*100:.1f}%" if isinstance(val, float) else str(val), "css_class": "up" if isinstance(val, (int, float)) and val > 0 else "down"})
            if "win_rate" in data:
                val = data["win_rate"]
                metrics.append({"label": "Win Rate", "value": f"{val*100:.1f}%" if isinstance(val, float) else str(val), "css_class": "up" if isinstance(val, (int, float)) and val > 0.5 else "warn"})
            if "cagr" in data:
                val = data["cagr"]
                metrics.append({"label": "CAGR", "value": f"{val*100:.1f}%" if isinstance(val, float) else str(val), "css_class": "up" if isinstance(val, (int, float)) and val > 0 else "down"})
            break  # Only first substantial backtest result
        except Exception:
            pass

    # Try go_no_go verdict
    verdict_file = archive_dir / "04_risk" / "go_no_go_verdict.md"
    if verdict_file.exists():
        text = verdict_file.read_text()
        if "GO" in text.upper() and "NO-GO" not in text.upper():
            metrics.insert(0, {"label": "Verdict", "value": "🟢 GO", "css_class": "up"})
        elif "NO-GO" in text.upper():
            metrics.insert(0, {"label": "Verdict", "value": "🔴 NO-GO", "css_class": "down"})

    return metrics


def _collect_stage_data(archive_dir: Path, run_id: str) -> List[Dict[str, Any]]:
    """Collect files per stage from archive directory."""
    stages = []
    stage_configs = [
        ("01_hypothesis", "📚", "Hypothesis"),
        ("02_data", "🔧", "Data Engineering"),
        ("03_backtest", "📈", "Backtest"),
        ("04_risk", "🛡️", "Risk Audit"),
        ("05_strategy", "✍️", "Strategy"),
    ]

    global_chart_idx = 0
    all_charts = []

    for ws_name, emoji, display_name in stage_configs:
        ws_path = archive_dir / ws_name
        if not ws_path.exists():
            continue

        md_files = sorted(ws_path.rglob("*.md"))
        png_files = sorted(ws_path.rglob("*.png"))
        json_files = sorted([f for f in ws_path.rglob("*.json") if f.stat().st_size < 100_000])

        # Bilingual detection
        zh_files = [f for f in md_files if "_en.md" not in f.name and f.name.endswith(".md")]
        en_files = [f for f in md_files if f.name.endswith("_en.md")]

        # Build relative paths for images
        charts = []
        for png in png_files:
            global_chart_idx += 1
            rel = png.relative_to(archive_dir)
            charts.append({
                "name": png.stem,
                "src": str(rel).replace("\\", "/"),
                "global_idx": global_chart_idx,
            })
            all_charts.append({"title": png.stem.replace("_", " ").title()})

        stage_data = {
            "id": ws_name.replace("0", "").replace("_", "-"),
            "name": display_name,
            "emoji": emoji,
            "file_count": len(md_files) + len(png_files) + len(json_files),
            "has_bilingual": bool(en_files),
            "charts": charts,
        }

        if stage_data["has_bilingual"]:
            # Pair up zh/en files
            zh_content = ""
            for zf in zh_files:
                zh_content += f"\n\n---\n\n## {zf.stem}\n\n"
                zh_content += zf.read_text()
            en_content = ""
            for ef in en_files:
                en_content += f"\n\n---\n\n## {ef.stem.replace('_en', '')}\n\n"
                en_content += ef.read_text()
            stage_data["content_zh"] = _md_to_html(zh_content)
            stage_data["content_en"] = _md_to_html(en_content)
        else:
            content = ""
            for mf in md_files:
                content += f"\n\n---\n\n## {mf.stem}\n\n"
                content += mf.read_text()
            stage_data["content"] = _md_to_html(content)

        stages.append(stage_data)

    return stages, all_charts


def generate_html_report(
    run_id: str,
    topic: str,
    workspace_root: Path,
    archive_root: Path,
) -> Path:
    """Generate the final HTML report for a completed run."""
    from jinja2 import Template

    archive_dir = archive_root / run_id
    if not archive_dir.exists():
        raise FileNotFoundError(f"Archive directory not found: {archive_dir}")

    stages, all_charts = _collect_stage_data(archive_dir, run_id)
    metrics = _extract_metrics(archive_dir)

    # If no metrics found, add placeholders
    if not metrics:
        metrics = [
            {"label": "Status", "value": "✅ Completed", "css_class": "up"},
            {"label": "Stages", "value": str(len(stages)), "css_class": ""},
        ]

    template = Template(_REPORT_TEMPLATE)
    html = template.render(
        run_id=run_id,
        topic=topic,
        completed_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        stage_count=len(stages),
        metrics=metrics,
        stages=stages,
        all_charts=all_charts,
    )

    output_path = archive_dir / "final_report.html"
    output_path.write_text(html, encoding="utf-8")
    return output_path
