import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sources.wiley import WileySource

def test_wiley_source_name():
    src = WileySource(tdm_token="test", journals=["Journal of Finance"])
    assert src.name == "wiley"
