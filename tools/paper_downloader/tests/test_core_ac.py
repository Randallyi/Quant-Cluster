import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sources.core_ac import CoreSource

def test_core_source_name():
    src = CoreSource(api_key="test", queries=["test"])
    assert src.name == "core_ac"
