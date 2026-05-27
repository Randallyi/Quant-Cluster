import pytest
from factors.core.meta import factor, FactorMeta, REGISTRY, unregister

@pytest.fixture(autouse=True)
def clean_registry():
    keys_before = set(REGISTRY.keys())
    yield
    for key in set(REGISTRY.keys()) - keys_before:
        unregister(key)

def test_factor_decorator_registers_meta():
    @factor(name="test.mom", category="test", inputs=["close"], outputs=["mom"])
    def test_mom(close):
        return close.pct_change(20)
    assert "test.mom" in REGISTRY
    meta = REGISTRY["test.mom"]
    assert isinstance(meta, FactorMeta)
    assert meta.name == "test.mom"

def test_factor_decorator_preserves_function():
    @factor(name="test.smb", category="test", inputs=["close"], outputs=["smb"])
    def test_smb(close):
        return close
    import pandas as pd
    df = pd.DataFrame({"A": [1.0, 2.0]})
    result = test_smb(df)
    assert result is not None
