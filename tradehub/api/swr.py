"""Stale-while-revalidate cache for slow read-only endpoint payloads.

Several page payloads are composed live from Postgres on every request
(the 15-minute rule record took 9-12s a hit, the gap desk ~5s and
intermittently 500s on statement timeouts). The data behind them changes
on a job cadence (5 minutes for the fifteen record, paused for the gap
desk), so serving a recent copy is exact, not approximate.

Semantics, per cache instance:
- fresh (age < ttl): serve the cached payload, never rebuild.
- stale: serve the cached payload immediately and start ONE background
  rebuild; concurrent requests never wait for it and never start a
  second one. A failed rebuild keeps serving the last good payload and
  suppresses further attempts for `retry_seconds`.
- cold (nothing cached yet): build synchronously under the lock, so a
  burst of first visitors shares one build instead of stampeding the
  database. A cold failure propagates to the caller (the endpoint's own
  error handling decides what the visitor sees) -- there is no last-good
  payload to serve.

Keyed on the Supabase client object's identity, like `_ttl_by_client`:
a different client (a test's fake) never sees another client's payload.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

T = TypeVar("T")


class SwrCache:
    def __init__(self, ttl_seconds: float, *, retry_seconds: float = 30.0,
                 clock: Callable[[], float] = time.monotonic):
        self._ttl = float(ttl_seconds)
        self._retry_seconds = float(retry_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._client: object = None
        self._value: T | None = None
        self._at = 0.0
        self._has = False
        self._building = False
        self._retry_after = 0.0
        self.last_error: Exception | None = None

    def get(self, builder: Callable[[], T], *, client: object = None) -> T:
        if client is None:
            # No client identity to key on (an unconfigured server, whose
            # payload is the fail-soft empty record anyway): never cache.
            return builder()
        with self._lock:
            if client is not None and self._client is not None and client is not self._client:
                self._value, self._has, self._at = None, False, 0.0
            if self._has:
                if self._clock() - self._at < self._ttl:
                    return self._value  # type: ignore[return-value]
                if not self._building and self._clock() >= self._retry_after:
                    self._building = True
                    threading.Thread(target=self._rebuild, args=(builder, client),
                                     daemon=True).start()
                return self._value  # type: ignore[return-value]
            # Cold: build while holding the lock so concurrent first
            # visitors wait for this one build instead of each starting
            # their own. The lock is per-cache, so other endpoints are
            # unaffected.
            try:
                value = builder()
            except Exception as exc:
                self.last_error = exc
                raise
            self._value, self._at, self._has, self._client = value, self._clock(), True, client
            return value

    def _rebuild(self, builder: Callable[[], T], client: object) -> None:
        try:
            value = builder()
        except Exception as exc:  # noqa: BLE001 -- a failed rebuild never reaches a visitor
            with self._lock:
                self.last_error = exc
                self._retry_after = self._clock() + self._retry_seconds
                self._building = False
            return
        with self._lock:
            self._value, self._at, self._has, self._client = value, self._clock(), True, client
            self._building = False
