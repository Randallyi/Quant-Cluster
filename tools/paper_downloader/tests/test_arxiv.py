import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sources.arxiv import ArxivSource, parse_arxiv_id
from datetime import datetime


def test_arxiv_source_name():
    src = ArxivSource("q-fin.TR")
    assert src.name == "arxiv_qfin_tr"


def test_parse_arxiv_id_from_url():
    assert parse_arxiv_id("http://arxiv.org/abs/2306.16127") == "2306.16127"
    assert parse_arxiv_id("https://arxiv.org/abs/2306.16127v2") == "2306.16127v2"
