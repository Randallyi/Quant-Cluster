"""YFinance data router — historical bars and fundamental data."""

import logging
import time
import uuid
from typing import Union

from fastapi import APIRouter

from cache.manager import CacheManager
from loaders.yfinance_loader import YFinanceLoader
from models import Bar, DataErrorResponse, DataResponse, FundamentalData, YFHistoricalRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/yfinance", tags=["yfinance"])

_loader = YFinanceLoader()
_cache = CacheManager()  # Uses default DB path


def _yf_key_params(request: YFHistoricalRequest):
    """Build a fake HistoricalDataRequest for cache key purposes."""
    from models import Contract, HistoricalDataRequest

    contract = Contract(
        symbol=request.ticker,
        secType="STK",
        exchange="YF",
        currency="USD",
    )
    return HistoricalDataRequest(
        contract=contract,
        durationStr="1 Y",
        barSizeSetting="1 day",
        endDateTime=request.end,
    )


def _map_interval(interval: str) -> str:
    mapping = {"1d": "1 day", "1wk": "1 week", "1mo": "1 month"}
    return mapping.get(interval, "1 day")


@router.post("/historical", response_model=Union[DataResponse, DataErrorResponse])
async def yf_historical(request: YFHistoricalRequest):
    request_id = uuid.uuid4().hex
    logger.info(
        "[%s] YF historical: %s %s-%s (%s)",
        request_id,
        request.ticker,
        request.start,
        request.end,
        request.interval,
    )

    cache_req = _yf_key_params(request)
    cache_req.barSizeSetting = _map_interval(request.interval)

    # Cache read-through
    try:
        cached = _cache.get(cache_req, source="yfinance")
    except Exception as exc:
        logger.warning("[%s] Cache read failed: %s", request_id, exc)
        cached = None

    if cached is not None:
        logger.info("[%s] Cache hit — %d bars", request_id, len(cached))
        return DataResponse(
            status="success",
            source="yfinance",
            request_id=request_id,
            data=[b.model_dump() for b in cached],
            metadata={},
            cached=True,
            fetch_time_ms=0,
        )

    # Fetch from yfinance
    start_time = time.perf_counter()
    try:
        bars = _loader.fetch_historical(
            ticker=request.ticker,
            start=request.start,
            end=request.end,
            interval=request.interval,
            auto_adjust=request.auto_adjust,
        )
        fetch_time_ms = int((time.perf_counter() - start_time) * 1000)

        if not bars:
            return DataErrorResponse(
                status="error",
                source="yfinance",
                request_id=request_id,
                attempts=1,
                error_code="NO_DATA_AVAILABLE",
                error_category="DATA_UNAVAILABLE",
                message=f"No data available for {request.ticker}",
                suggestion="Check ticker symbol or date range.",
                fallback_available=["ibkr"],
            )

        # Cache write-through
        try:
            _cache.set(cache_req, bars, source="yfinance")
        except Exception as exc:
            logger.warning("[%s] Cache write failed: %s", request_id, exc)

        return DataResponse(
            status="success",
            source="yfinance",
            request_id=request_id,
            data=[b.model_dump() for b in bars],
            metadata={},
            cached=False,
            fetch_time_ms=fetch_time_ms,
        )

    except Exception as exc:
        fetch_time_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error("[%s] YF fetch failed: %s", request_id, exc)
        return DataErrorResponse(
            status="error",
            source="yfinance",
            request_id=request_id,
            attempts=1,
            error_code="FETCH_ERROR",
            error_category="NETWORK",
            message=str(exc),
            suggestion="Check network or try again later.",
            fallback_available=["ibkr"],
        )


@router.get("/fundamental/{ticker}", response_model=Union[DataResponse, DataErrorResponse])
async def yf_fundamental(ticker: str):
    request_id = uuid.uuid4().hex
    logger.info("[%s] YF fundamental: %s", request_id, ticker)

    start_time = time.perf_counter()
    try:
        fund = _loader.fetch_fundamental(ticker)
        fetch_time_ms = int((time.perf_counter() - start_time) * 1000)

        if fund is None:
            return DataErrorResponse(
                status="error",
                source="yfinance",
                request_id=request_id,
                attempts=1,
                error_code="NO_DATA_AVAILABLE",
                error_category="DATA_UNAVAILABLE",
                message=f"No fundamental data for {ticker}",
                suggestion="Check ticker symbol.",
                fallback_available=[],
            )

        return DataResponse(
            status="success",
            source="yfinance",
            request_id=request_id,
            data=[fund.model_dump()],
            metadata={},
            cached=False,
            fetch_time_ms=fetch_time_ms,
        )

    except Exception as exc:
        fetch_time_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error("[%s] YF fundamental failed: %s", request_id, exc)
        return DataErrorResponse(
            status="error",
            source="yfinance",
            request_id=request_id,
            attempts=1,
            error_code="FETCH_ERROR",
            error_category="NETWORK",
            message=str(exc),
            suggestion="Check network or try again later.",
            fallback_available=[],
        )
