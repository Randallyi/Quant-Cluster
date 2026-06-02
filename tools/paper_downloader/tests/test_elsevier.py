import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sources.elsevier import ElsevierSource

def test_elsevier_source_name():
    src = ElsevierSource(api_key="test", journals=["JFE"])
    assert src.name == "elsevier"
