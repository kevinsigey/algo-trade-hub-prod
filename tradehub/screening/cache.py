"""Tiny file cache with TTL. Pickle for frames/objects, JSON for scalars.

A stale entry is treated as absent (refetch); a failed refetch surfaces to the
caller as a missing field with a reason — the cache never invents data.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import re
import time
from pathlib import Path


class Cache:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str, ext: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", key)[:120]
        digest = hashlib.md5(key.encode()).hexdigest()[:10]
        return self.root / f"{safe}__{digest}.{ext}"

    def get(self, key: str, ttl_hours: float):
        for ext, loader in (("pkl", "pickle"), ("json", "json")):
            p = self._path(key, ext)
            if p.exists() and (time.time() - p.stat().st_mtime) <= ttl_hours * 3600:
                try:
                    if loader == "pickle":
                        with open(p, "rb") as f:
                            return pickle.load(f)
                    with open(p) as f:
                        return json.load(f)
                except Exception:
                    return None
        return None

    def set(self, key: str, obj) -> None:
        try:
            p = self._path(key, "pkl")
            with open(p, "wb") as f:
                pickle.dump(obj, f)
        except Exception:
            pass  # cache is an optimization; failure to cache is not fatal
