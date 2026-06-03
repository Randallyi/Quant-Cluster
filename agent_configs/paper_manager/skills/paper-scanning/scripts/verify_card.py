"""
验证论文卡片格式是否符合规范。
"""

from pathlib import Path
from typing import Dict, List

import yaml


REQUIRED_FIELDS = ["doc_id", "title", "authors", "year", "source", "source_tier", "paper_type"]
VALID_SOURCE_TIERS = {"journal", "ssrn", "arxiv"}
VALID_PAPER_TYPES = {"quantitative", "theoretical", "review", "empirical_non_quant", "other"}
QUANT_REQUIRED_SECTIONS = [
    "量化深度分析",
    "方法论可信度评分",
    "可迁移性评估",
    "因子与回测",
    "关键发现",
    "方法论风险",
]


def parse_frontmatter(card_path: Path) -> Dict:
    """读取 markdown 文件，解析 YAML frontmatter（--- 之间的文本）。"""
    try:
        content = card_path.read_text(encoding="utf-8")
    except Exception:
        return {}

    if not content.startswith("---"):
        return {}

    # Find the closing ---
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return {}

    fm_text = content[3:end_idx].strip()
    try:
        return yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return {}


def verify_card(card_path: Path) -> Dict:
    """验证卡片 frontmatter 和正文结构。"""
    errors: List[str] = []

    if not card_path.exists():
        return {"valid": False, "errors": [f"File not found: {card_path}"]}

    frontmatter = parse_frontmatter(card_path)
    if not frontmatter:
        return {"valid": False, "errors": ["Invalid or missing YAML frontmatter"]}

    # Required fields
    for field in REQUIRED_FIELDS:
        if field not in frontmatter or frontmatter[field] is None:
            errors.append(f"Missing required field: {field}")

    # source_tier enum
    source_tier = frontmatter.get("source_tier")
    if source_tier is not None and source_tier not in VALID_SOURCE_TIERS:
        errors.append(f"Invalid source_tier: {source_tier}. Must be one of {VALID_SOURCE_TIERS}")

    # paper_type enum
    paper_type = frontmatter.get("paper_type")
    if paper_type is not None and paper_type not in VALID_PAPER_TYPES:
        errors.append(f"Invalid paper_type: {paper_type}. Must be one of {VALID_PAPER_TYPES}")

    # For quantitative papers, check required sections
    if paper_type == "quantitative":
        try:
            body = card_path.read_text(encoding="utf-8")
        except Exception as exc:
            errors.append(f"Cannot read card body: {exc}")
            body = ""

        for section in QUANT_REQUIRED_SECTIONS:
            if f"## {section}" not in body:
                errors.append(f"Missing required quantitative section: {section}")

    return {"valid": len(errors) == 0, "errors": errors}
