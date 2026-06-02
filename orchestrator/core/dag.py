"""DAG definition — agents, dependencies, and execution order."""
from pathlib import Path

AGENTS = {
    "hypothesis":     {"port": 8642, "api_key": "sk-hypothesis-local", "workspace": "01_hypothesis"},
    "data_engineer":  {"port": 8643, "api_key": "sk-data-local",       "workspace": "02_data"},
    "quant_analyst":  {"port": 8644, "api_key": "sk-quant-local",      "workspace": "03_backtest"},
    "risk_auditor":   {"port": 8645, "api_key": "sk-risk-local",       "workspace": "04_risk"},
    "strategy_writer":{"port": 8646, "api_key": "sk-writer-local",     "workspace": "05_strategy"},
    "paper_manager": {"port": 8647, "api_key": "sk-downloader-local", "workspace": "papers"},
}

DAG = {
    "hypothesis": {
        "deps": [],
        "output_files": ["hypothesis_*.md", "hypothesis_*_en.md", "data_requirements.json", ".agent_checkpoint.json"],
        "prompt_template": "研究主题：{topic}\n请完成文献调研并提出可检验假设。输出到 /workspace/01_hypothesis/",
    },
    "data_engineer": {
        "deps": ["hypothesis"],
        "output_files": ["feature_matrix_*.parquet", "dataset_metadata.json", "data_quality_report_*.md", "data_quality_report_*_en.md", ".agent_checkpoint.json"],
        "prompt_template": "数据需求清单已就绪。请读取 /workspace/01_hypothesis/data_requirements.json 并完成数据工程任务。输出到 /workspace/02_data/",
    },
    "quant_analyst": {
        "deps": ["data_engineer"],
        "output_files": ["backtest_results_*.json", "backtest_report_*.md", "backtest_report_*_en.md", "equity_curve_*.csv", ".agent_checkpoint.json"],
        "prompt_template": "特征矩阵已就绪。请读取 /workspace/02_data/ 下的产物并完成回测建模。输出到 /workspace/03_backtest/",
    },
    "risk_auditor": {
        "deps": ["quant_analyst"],
        "output_files": ["go_no_go_verdict.md", "go_no_go_verdict_en.md", "overfitting_diagnosis.md", "overfitting_diagnosis_en.md", "regime_analysis.md", "regime_analysis_en.md", ".agent_checkpoint.json"],
        "prompt_template": "回测结果已就绪。请读取 /workspace/03_backtest/ 下的产物并完成风控审计。输出到 /workspace/04_risk/",
    },
    "strategy_writer": {
        "deps": ["risk_auditor"],
        "output_files": ["trading_sop_*.md", "trading_sop_*_en.md", "strategy_failure_analysis.md", "strategy_failure_analysis_en.md", "strategy_metadata.json", ".agent_checkpoint.json"],
        "prompt_template": "审计结论已就绪。请读取 /workspace/04_risk/go_no_go_verdict.md 并撰写交易 SOP。输出到 /workspace/05_strategy/",
    },
}

EXECUTION_ORDER = ["hypothesis", "data_engineer", "quant_analyst", "risk_auditor", "strategy_writer"]

WORKSPACE_ROOT = Path(__file__).parent.parent.parent / "shared_workspace"
AGENT_CONFIG_ROOT = Path(__file__).parent.parent.parent / "agent_configs"
