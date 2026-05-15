from typing import List, Literal, Optional
from pydantic import BaseModel, Field


# Contract model — mirrors ib_insync Contract
class Contract(BaseModel):
    symbol: str
    secType: Literal["STK", "ETF", "OPT", "FUT", "CASH", "IND", "BOND", "FOP", "WAR", "CFD"]
    exchange: str
    currency: str = "USD"
    expiry: str = ""
    strike: float = 0.0
    right: Literal["", "C", "P"] = ""
    multiplier: str = ""
    localSymbol: str = ""
    primaryExchange: str = ""
    includeExpired: bool = False


# Historical data request — mirrors reqHistoricalData parameters
class HistoricalDataRequest(BaseModel):
    contract: Contract
    endDateTime: str = ""          # YYYYMMDD-HH:MM:SS or empty = current time
    durationStr: str = Field(pattern=r"^\d+ [SDWMY]$")  # e.g. "1 Y", "5 D"
    barSizeSetting: Literal[
        "1 secs", "5 secs", "10 secs", "15 secs", "30 secs",
        "1 min", "2 mins", "3 mins", "5 mins", "10 mins", "15 mins", "20 mins", "30 mins",
        "1 hour", "2 hours", "3 hours", "4 hours", "8 hours",
        "1 day", "1 week", "1 month"
    ]
    whatToShow: Literal[
        "TRADES", "MIDPOINT", "BID", "ASK", "BID_ASK",
        "ADJUSTED_LAST", "HISTORICAL_VOLATILITY", "OPTION_IMPLIED_VOLATILITY",
        "YIELD_BID", "YIELD_ASK", "YIELD_LAST", "SCHEDULE", "AGGTRADES"
    ] = "TRADES"
    useRTH: bool = True
    formatDate: int = 1
    keepUpToDate: bool = False


# Individual bar (OHLCV + extras)
class Bar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    wap: float
    count: int


# Success response
class HistoricalDataResponse(BaseModel):
    status: Literal["success", "error"]
    request_id: str
    source: str = "ibkr_tws"
    data_router_request_id: str
    contract: Contract
    barSizeSetting: str
    whatToShow: str
    durationStr: str
    useRTH: bool
    startDate: str
    endDate: str
    timeZone: str = "EST"
    rows: int
    bars: List[Bar]
    cached: bool = False
    fetch_time_ms: int = 0


# Error response
class DataErrorResponse(BaseModel):
    status: Literal["error"]
    request_id: str
    attempts: int
    error_code: str
    error_category: Literal["SUBSCRIPTION", "SYMBOL", "TIMEOUT", "NETWORK", "TWS_DISCONNECTED", "RATE_LIMIT", "INVALID_PARAMS", "DATA_UNAVAILABLE"]
    tws_error_code: Optional[int] = None
    message: str
    suggestion: str
    contract: Optional[Contract] = None
