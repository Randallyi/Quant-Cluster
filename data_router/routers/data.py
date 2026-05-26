"""Compatibility layer — forwards to /data/ibkr/historical."""

import logging
from typing import Union

from fastapi import APIRouter, Depends

from cache.manager import CacheManager
from dependencies import get_cache_manager, get_ibkr_client
from ibkr.client import IBKRClient
from models import DataErrorResponse, HistoricalDataRequest, HistoricalDataResponse
from .ibkr import historical_data as ibkr_historical_data

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/data", tags=["data"])


@router.post("/historical", response_model=Union[HistoricalDataResponse, DataErrorResponse])
async def historical_data(
    request: HistoricalDataRequest,
    client: IBKRClient = Depends(get_ibkr_client),
    cache: CacheManager = Depends(get_cache_manager),
):
    """DEPRECATED: Use /data/ibkr/historical instead."""
    logger.warning(
        "DEPRECATED: /data/historical is deprecated. Use /data/ibkr/historical instead. "
        "This endpoint will be removed in a future release."
    )
    return await ibkr_historical_data(request, client, cache)
