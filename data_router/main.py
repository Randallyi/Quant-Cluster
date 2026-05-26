"""FastAPI application factory for the data router."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from ib_insync import util as ib_util

# Allow ib_insync to run inside uvicorn's already-running event loop
ib_util.patchAsyncio()

from cache.manager import CacheManager
from ibkr.client import IBKRClient
from routers import data, ibkr, sources, yfinance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise TWS client and SQLite cache on startup."""
    host = os.getenv("TWS_HOST", "host.docker.internal")
    port = int(os.getenv("TWS_PORT", "7497"))

    # Ensure default loop == running loop so ib_insync's getLoop() works
    loop = asyncio.get_running_loop()
    asyncio.set_event_loop(loop)

    # TWS client — sync connect with nest_asyncio patched
    client = IBKRClient(host=host, port=port)
    app.state.ibkr_client = client

    # SQLite cache
    cache = CacheManager()
    app.state.cache = cache

    logger.info("Connecting to TWS at %s:%d ...", host, port)
    if client.connect():
        logger.info("TWS connected successfully")
    else:
        logger.warning("TWS connection failed on startup — will retry on first request")

    yield

    logger.info("Disconnecting from TWS ...")
    client.disconnect()
    logger.info("TWS disconnected")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title="Quant Cluster — Data Router",
        description="Multi-source historical data gateway for the quant trading cluster.",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.include_router(data.router)
    app.include_router(ibkr.router, prefix="/data")
    app.include_router(yfinance.router, prefix="/data")
    app.include_router(sources.router, prefix="/data")

    @app.get("/health")
    async def health():
        """Service + TWS connection health."""
        return app.state.ibkr_client.health()

    return app


app = create_app()
