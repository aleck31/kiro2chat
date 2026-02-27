"""Request statistics collector."""

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class RequestRecord:
    timestamp: float
    model: str
    latency_ms: float
    status: str  # "ok" / "error"
    error: str | None = None


class StatsCollector:
    """Thread-safe request statistics collector."""

    def __init__(self, maxlen: int = 100):
        self._lock = threading.Lock()
        self.recent_requests: deque[RequestRecord] = deque(maxlen=maxlen)
        self.total_requests: int = 0
        self.total_errors: int = 0
        self.total_latency: float = 0.0
        self.start_time: float = time.time()

    def record(
        self,
        model: str,
        latency_ms: float,
        status: str = "ok",
        error: str | None = None,
    ) -> None:
        rec = RequestRecord(
            timestamp=time.time(),
            model=model,
            latency_ms=latency_ms,
            status=status,
            error=error,
        )
        with self._lock:
            self.recent_requests.append(rec)
            self.total_requests += 1
            self.total_latency += latency_ms
            if status == "error":
                self.total_errors += 1

    def get_summary(self) -> dict:
        with self._lock:
            avg = (self.total_latency / self.total_requests) if self.total_requests else 0
            return {
                "total_requests": self.total_requests,
                "total_errors": self.total_errors,
                "total_success": self.total_requests - self.total_errors,
                "avg_latency_ms": round(avg, 1),
                "uptime_seconds": round(time.time() - self.start_time, 1),
            }

    def get_recent(self, n: int = 20) -> list[RequestRecord]:
        with self._lock:
            items = list(self.recent_requests)
            return items[-n:]


# Global singleton
stats = StatsCollector()
