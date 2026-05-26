"""IBKR historical data router."""

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Optional, Union

from fastapi import APIRouter, Depends
from ib_insync import Contract as IbContract

from cache.manager import CacheManager
from dependencies import get_cache_manager, get_ibkr_client
from ibkr.client import IBKRClient
from models import Bar, Contract, DataErrorResponse, HistoricalDataRequest, HistoricalDataResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ibkr", tags=["ibkr"])

BACKOFF_DELAYS = [2, 4, 8, 16, 32]


def _to_ib_contract(contract: Contract) -> IbContract:
    """Convert pydantic Contract to ib_insync Contract."""
    kwargs = {
        "symbol": contract.symbol,
        "secType": contract.secType,
        "exchange": contract.exchange,
        "currency": contract.currency,
        "lastTradeDateOrContractMonth": contract.expiry,
        "strike": contract.strike,
        "right": contract.right,
        "multiplier": contract.multiplier,
        "primaryExchange": contract.primaryExchange,
        "includeExpired": contract.includeExpired,
    }
    if contract.localSymbol:
        kwargs["localSymbol"] = contract.localSymbol
    return IbContract(**kwargs)


def _format_date(value) -> str:
    """Normalise TWS date to ISO string."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_tws_code(message: str) -> Optional[int]:
    """Best-effort extraction of a TWS error code from an exception message."""
    # look for common TWS error codes explicitly
    match = re.search(r"\b(502|504|322|2104|2106|200|162|354|366)\b", message)
    if match:
        return int(match.group(1))
    # fallback: grab the first 3-4 digit number that looks like an error code
    match = re.search(r"\b(\d{3,4})\b", message)
    if match:
        return int(match.group(1))
    return None


def _classify_error(exc: Exception) -> tuple:
    """Map an exception to (error_code, error_category, tws_error_code, message, suggestion)."""
    msg = str(exc)
    tws_code = _parse_tws_code(msg)

    if isinstance(exc, asyncio.TimeoutError):
        return (
            "REQUEST_TIMEOUT",
            "TIMEOUT",
            tws_code,
            msg,
            "Try again later or reduce request size.",
        )

    if isinstance(exc, ConnectionError) or tws_code == 504:
        return (
            "TWS_DISCONNECTED",
            "TWS_DISCONNECTED",
            tws_code or 504,
            msg,
            "Check TWS/Gateway is running and the API port is open.",
        )

    if tws_code == 502:
        return (
            "CONNECTION_FAILED",
            "NETWORK",
            502,
            msg,
            "Check TWS/Gateway is running and the API port is open.",
        )

    if tws_code in (322, 162):
        return (
            "RATE_LIMIT_EXCEEDED",
            "RATE_LIMIT",
            tws_code,
            msg,
            "Reduce request frequency or wait before retrying.",
        )

    if tws_code == 354:
        return (
            "SUBSCRIPTION_REQUIRED",
            "SUBSCRIPTION",
            354,
            msg,
            "Verify market data subscription for this symbol/exchange.",
        )

    if tws_code == 200:
        return (
            "INVALID_SYMBOL",
            "SYMBOL",
            200,
            msg,
            "Check contract symbol, exchange, and security type.",
        )

    if tws_code == 366:
        return (
            "NO_DATA_AVAILABLE",
            "DATA_UNAVAILABLE",
            366,
            msg,
            "No historical data available for this contract and time range.",
        )

    return (
        "UNKNOWN_ERROR",
        "NETWORK",
        tws_code,
        msg,
        "Check TWS logs or contact support.",
    )


@router.post("/historical", response_model=Union[HistoricalDataResponse, DataErrorResponse])
async def historical_data(
    request: HistoricalDataRequest,
    client: IBKRClient = Depends(get_ibkr_client),
    cache: CacheManager = Depends(get_cache_manager),
) -> Union[HistoricalDataResponse, DataErrorResponse]:
    """Fetch historical bars from IBKR with mechanical retries."""
    request_id = uuid.uuid4().hex
    logger.info(
        "[%s] Historical data request: %s %s %s",
        request_id,
        request.contract.symbol,
        request.barSizeSetting,
        request.durationStr,
    )

    # --- cache read-through -------------------------------------------
    try:
        cached_bars = cache.get(request, source="ibkr")
    except Exception as exc:
        logger.warning("[%s] Cache read failed: %s", request_id, exc)
        cached_bars = None

    if cached_bars is not None:
        logger.info("[%s] Cache hit — %d bars", request_id, len(cached_bars))
        start_date = cached_bars[0].date if cached_bars else ""
        end_date = cached_bars[-1].date if cached_bars else ""
        return HistoricalDataResponse(
            status="success",
            request_id=request_id,
            source="ibkr",
            data_router_request_id=request_id,
            contract=request.contract,
            barSizeSetting=request.barSizeSetting,
            whatToShow=request.whatToShow,
            durationStr=request.durationStr,
            useRTH=request.useRTH,
            startDate=start_date,
            endDate=end_date,
            timeZone="EST",
            rows=len(cached_bars),
            bars=cached_bars,
            cached=True,
            fetch_time_ms=0,
        )

    # Acquire a clientId from the pool (currently always the main clientId=100).
    try:
        client_id = client.pool.acquire()
    except Exception as exc:
        logger.error("[%s] Pool exhausted: %s", request_id, exc)
        return DataErrorResponse(
            status="error",
            request_id=request_id,
            attempts=0,
            error_code="POOL_EXHAUSTED",
            error_category="RATE_LIMIT",
            tws_error_code=None,
            message=str(exc),
            suggestion="Wait for an available connection or scale up the client pool.",
            contract=request.contract,
        )

    ib_contract = _to_ib_contract(request.contract)
    bars: list[Bar] = []
    last_exception: Optional[Exception] = None
    error_meta: Optional[tuple] = None
    fetch_time_ms = 0

    try:
        start_time = time.perf_counter()

        for attempt in range(6):  # 1 initial + 5 retries
            if attempt > 0:
                delay = BACKOFF_DELAYS[attempt - 1]
                logger.warning(
                    "[%s] Retry %d/5 after %ds: %s",
                    request_id,
                    attempt,
                    delay,
                    last_exception,
                )
                await asyncio.sleep(delay)

            try:
                if not client.is_connected():
                    client.connect()
                ib = client.get_ib()
                bar_data_list = await ib.reqHistoricalDataAsync(
                    ib_contract,
                    endDateTime=request.endDateTime or "",
                    durationStr=request.durationStr,
                    barSizeSetting=request.barSizeSetting,
                    whatToShow=request.whatToShow,
                    useRTH=request.useRTH,
                    formatDate=request.formatDate,
                )

                if bar_data_list:
                    for b in bar_data_list:
                        bars.append(
                            Bar(
                                date=_format_date(b.date),
                                open=b.open,
                                high=b.high,
                                low=b.low,
                                close=b.close,
                                volume=int(b.volume) if b.volume is not None else 0,
                                wap=b.average if b.average is not None else 0.0,
                                count=int(b.barCount) if b.barCount is not None else 0,
                            )
                        )

                fetch_time_ms = int((time.perf_counter() - start_time) * 1000)
                logger.info(
                    "[%s] Fetched %d bars in %dms", request_id, len(bars), fetch_time_ms
                )
                # --- cache write-through ----------------------------
                if bars:
                    try:
                        cache.set(request, bars, source="ibkr")
                    except Exception as exc:
                        logger.warning("[%s] Cache write failed: %s", request_id, exc)
                break

            except Exception as exc:
                last_exception = exc
                error_meta = _classify_error(exc)
                logger.warning(
                    "[%s] Attempt %d failed: %s", request_id, attempt + 1, exc
                )
        else:
            # All attempts exhausted
            fetch_time_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("[%s] All retries failed after %dms", request_id, fetch_time_ms)
            return DataErrorResponse(
                status="error",
                request_id=request_id,
                attempts=6,
                error_code=error_meta[0] if error_meta else "UNKNOWN_ERROR",
                error_category=error_meta[1] if error_meta else "NETWORK",
                tws_error_code=error_meta[2] if error_meta else None,
                message=error_meta[3] if error_meta else str(last_exception),
                suggestion=error_meta[4] if error_meta else "Check TWS logs or contact support.",
                contract=request.contract,
            )

    finally:
        client.pool.release(client_id)

    start_date = bars[0].date if bars else ""
    end_date = bars[-1].date if bars else ""

    return HistoricalDataResponse(
        status="success",
        request_id=request_id,
        source="ibkr",
        data_router_request_id=request_id,
        contract=request.contract,
        barSizeSetting=request.barSizeSetting,
        whatToShow=request.whatToShow,
        durationStr=request.durationStr,
        useRTH=request.useRTH,
        startDate=start_date,
        endDate=end_date,
        timeZone="EST",
        rows=len(bars),
        bars=bars,
        cached=False,
        fetch_time_ms=fetch_time_ms,
    )
