import threading


class PoolExhausted(Exception):
    pass


class ClientIdPool:
    """TWS API requires unique clientId per connection. data_router uses 100-109."""
    
    def __init__(self, start: int = 100, end: int = 109):
        self.available = list(range(start, end + 1))
        self.in_use = set()
        self.lock = threading.Lock()

    def acquire(self) -> int:
        with self.lock:
            if not self.available:
                raise PoolExhausted("All TWS clientIds in use")
            cid = self.available.pop(0)
            self.in_use.add(cid)
            return cid

    def release(self, cid: int):
        with self.lock:
            self.in_use.discard(cid)
            if cid not in self.available:
                self.available.append(cid)

    def status(self) -> dict:
        with self.lock:
            return {
                "available": len(self.available),
                "in_use": len(self.in_use),
                "available_ids": self.available.copy(),
                "in_use_ids": list(self.in_use),
            }
