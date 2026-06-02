import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sources.conference import NeurIPSSource

def test_neurips_name():
    src = NeurIPSSource(year=2024)
    assert src.name == "neurips_2024"
