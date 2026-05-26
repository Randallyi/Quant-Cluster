import pytest

from loaders.yfinance_loader import YFinanceLoader
from models import Bar


def _is_rate_limit(exc):
    return "Rate limit" in str(exc) or "Too Many Requests" in str(exc)


class TestYFinanceLoader:
    @pytest.fixture
    def loader(self):
        return YFinanceLoader()

    def test_name(self, loader):
        assert loader.name == "yfinance"

    def test_fetch_historical_aapl(self, loader):
        """Integration test: fetch real AAPL data. May be slow / flaky."""
        try:
            bars = loader.fetch_historical("AAPL", start="2024-01-01", end="2024-01-10")
        except Exception as exc:
            if _is_rate_limit(exc):
                pytest.skip("Yahoo Finance rate limited")
            raise
        assert isinstance(bars, list)
        if len(bars) > 0:
            assert isinstance(bars[0], Bar)
            assert bars[0].open > 0
            assert bars[0].volume >= 0

    def test_fetch_historical_invalid_ticker(self, loader):
        try:
            bars = loader.fetch_historical("INVALID_TICKER_XYZ", start="2024-01-01", end="2024-01-10")
        except Exception as exc:
            if _is_rate_limit(exc):
                pytest.skip("Yahoo Finance rate limited")
            raise
        assert bars == []

    def test_fetch_fundamental_aapl(self, loader):
        try:
            fund = loader.fetch_fundamental("AAPL")
        except Exception as exc:
            if _is_rate_limit(exc):
                pytest.skip("Yahoo Finance rate limited")
            raise
        if fund is not None:
            assert fund.ticker == "AAPL"
            assert any([
                fund.market_cap is not None,
                fund.pe_ratio is not None,
                fund.pb_ratio is not None,
                fund.eps is not None,
            ])

    def test_health(self, loader):
        health = loader.health()
        assert "available" in health
        assert "latency_ms" in health
        assert "message" in health


class TestAKShareLoader:
    def test_name(self):
        from loaders.akshare_loader import AKShareLoader
        loader = AKShareLoader()
        assert loader.name == "akshare"

    def test_health_not_available(self):
        from loaders.akshare_loader import AKShareLoader
        loader = AKShareLoader()
        health = loader.health()
        assert health["available"] is False
