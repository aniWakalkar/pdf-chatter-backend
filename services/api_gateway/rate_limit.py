import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False, max(1, int(window_seconds - (now - hits[0])))
        hits.append(now)
        return True, 0


RULES: list[tuple[str, str, int, int]] = [
    ("POST", "/api/auth/login", 10, 60),
    ("POST", "/api/auth/register", 5, 60),
    ("POST", "/api/documents", 10, 60),
    ("POST", "/api/chat", 20, 60),
]


def match_rule(method: str, path: str) -> tuple[int, int] | None:
    for rule_method, rule_path, limit, window in RULES:
        if method == rule_method and path.rstrip("/") == rule_path:
            return limit, window
    return None
