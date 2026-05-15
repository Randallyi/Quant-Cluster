import logging
from ib_insync import IB

from .connection_pool import ClientIdPool, PoolExhausted

logger = logging.getLogger(__name__)


class IBKRClient:
    def __init__(self, host: str = "host.docker.internal", port: int = 7497):
        self.host = host
        self.port = port
        self.pool = ClientIdPool(start=100, end=109)
        self._main_client: IB = None
        self._main_client_id = 100
        self._connected = False

    def connect(self) -> bool:
        """Establish persistent connection with clientId=100"""
        if self._connected and self._main_client and self._main_client.isConnected():
            return True
        try:
            self._main_client = IB()
            self._main_client.connect(self.host, self.port, clientId=self._main_client_id)
            self._connected = True
            logger.info(f"TWS connected: {self.host}:{self.port} (clientId={self._main_client_id})")
            return True
        except Exception as e:
            logger.error(f"TWS connection failed: {e}")
            self._connected = False
            return False

    def disconnect(self):
        if self._main_client and self._main_client.isConnected():
            self._main_client.disconnect()
            self._connected = False
            logger.info("TWS disconnected")

    def is_connected(self) -> bool:
        return self._connected and self._main_client is not None and self._main_client.isConnected()

    def get_ib(self) -> IB:
        if not self.is_connected():
            if not self.connect():
                raise ConnectionError("Cannot connect to TWS")
        return self._main_client

    def health(self) -> dict:
        return {
            "connected": self.is_connected(),
            "host": self.host,
            "port": self.port,
            "client_id": self._main_client_id,
            "pool": self.pool.status(),
        }
