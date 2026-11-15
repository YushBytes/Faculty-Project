"""Failed sign-in throttle: slows password guessing against one account.

After ``LOGIN_MAX_FAILURES`` wrong passwords for the same email within
``LOGIN_WINDOW_SECONDS``, further attempts for that email are refused with 429 until the oldest
failure in the window ages out -- the correct password included, so guessing cannot continue by
waiting for a lucky hit. A successful sign-in clears the count.

Keyed on the normalised email, not the client address: every browser request reaches the API
through the web server, so the API sees one address for everyone and an address key would lock
out the whole institution at once. Unknown emails are counted exactly like known ones, so the
throttle does not reveal which accounts exist.

Deliberate limits, documented in docs/SECURITY_AUDIT.md:

- State lives in this process. The API runs one uvicorn process (backend/Dockerfile); with
  several, each keeps its own count, so put a rate limit at the reverse proxy as well.
- Someone who knows an email can keep that account locked by failing on purpose. The window is
  short and fixed (it does not grow), and an administrator can still reset the password.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

from app.core.config import get_settings

_MAX_TRACKED = 10_000  # bound memory under a spray of random emails


class LoginThrottle:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _window(self) -> tuple[int, int]:
        settings = get_settings()
        return settings.login_max_failures, settings.login_window_seconds

    def _recent(self, key: str, now: float, window: int) -> deque[float]:
        times = self._failures.get(key)
        if times is None:
            return deque()
        while times and now - times[0] >= window:
            times.popleft()
        if not times:
            del self._failures[key]
        return times

    def retry_after(self, key: str) -> int | None:
        """Seconds until ``key`` may try again, or None when it is not throttled."""
        limit, window = self._window()
        if limit <= 0:
            return None
        with self._lock:
            now = self._clock()
            times = self._recent(key, now, window)
            if len(times) < limit:
                return None
            return max(1, int(window - (now - times[0])) + 1)

    def failed(self, key: str) -> None:
        limit, window = self._window()
        if limit <= 0:
            return
        with self._lock:
            now = self._clock()
            if key not in self._failures and len(self._failures) >= _MAX_TRACKED:
                for stale in [
                    k for k, v in self._failures.items() if not v or now - v[-1] >= window
                ]:
                    del self._failures[stale]
                if len(self._failures) >= _MAX_TRACKED:
                    self._failures.pop(next(iter(self._failures)))
            self._failures.setdefault(key, deque()).append(now)

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_throttle = LoginThrottle()
