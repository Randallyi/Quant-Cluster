import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from sources.base import Source


def test_source_abc_cannot_instantiate():
    try:
        s = Source()
        assert False, "Should raise TypeError"
    except TypeError:
        pass
