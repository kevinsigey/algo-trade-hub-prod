"""Machine API keys (phase-2 spec §1.2/§1.5): issue, verify, revoke, audit.

The key itself is never stored -- only its SHA-256 hash -- and is shown exactly once, at
creation, to the signed-in admin. Verification is fail-closed in the admin-auth style: an
unknown key, a revoked key and a malformed key are all the same answer (None). Keys are
created and revoked only through the admin routes in main.py; nothing in this module is
reachable with a machine key, so a key can never mint or widen another key.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

KEYS = "api_keys"
EVENTS = "api_key_events"

ALLOWED_SCOPES = ("orders:place", "orders:read", "portfolio:read")
_KEY_RE = re.compile(r"^thk_[0-9a-f]{32}$")
_LAST_USED_WRITE_EVERY = timedelta(seconds=60)

_PUBLIC_COLUMNS = "id,label,scopes,max_qty,max_notional,daily_cap,created_at,last_used_at,revoked_at"


def generate_key() -> str:
    """`thk_<32 hex>` from a CSPRNG (spec §1.2)."""
    return "thk_" + secrets.token_hex(16)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _public(row: dict) -> dict:
    """A key row with the hash stripped: hashes never leave the server, even to the admin UI.
    The nullable lifecycle fields are always present (null until used), so consumers never
    have to guess whether a missing field means 'not yet' or 'not returned'."""
    out = {k: v for k, v in row.items() if k != "key_hash"}
    out.setdefault("last_used_at", None)
    out.setdefault("revoked_at", None)
    return out


def _validate_scopes(scopes) -> list[str]:
    wanted = list(dict.fromkeys(scopes or []))
    if not wanted:
        raise ValueError("a key needs at least one scope")
    unknown = [s for s in wanted if s not in ALLOWED_SCOPES]
    if unknown:
        raise ValueError(f"unknown scope(s): {', '.join(unknown)} (allowed: {', '.join(ALLOWED_SCOPES)})")
    return [s for s in ALLOWED_SCOPES if s in wanted]


def create_key(supa, label: str, scopes, *, max_qty: int = 100, max_notional: float = 25000,
               daily_cap: int = 50) -> tuple[dict, str]:
    """Insert a key row; return (public row, plaintext). The plaintext exists only in this
    return value -- the row holds its hash. Caps are Kevin's, set here at creation; no code
    path lets a key raise its own."""
    label = (label or "").strip()
    if not 1 <= len(label) <= 60:
        raise ValueError("label must be 1-60 characters")
    scopes = _validate_scopes(scopes)
    if int(max_qty) <= 0 or float(max_notional) <= 0 or int(daily_cap) <= 0:
        raise ValueError("caps must be positive")
    plaintext = generate_key()
    row = supa.table(KEYS).insert({
        "label": label, "key_hash": hash_key(plaintext), "scopes": scopes,
        "max_qty": int(max_qty), "max_notional": float(max_notional), "daily_cap": int(daily_cap),
    }).execute().data[0]
    record_event(supa, row["id"], "admin/keys", "created", detail=label)
    return _public(row), plaintext


def list_keys(supa) -> list[dict]:
    rows = supa.table(KEYS).select(_PUBLIC_COLUMNS).order("created_at", desc=True).execute().data
    return [_public(r) for r in rows]


def get_key(supa, key_id: int) -> dict | None:
    rows = supa.table(KEYS).select(_PUBLIC_COLUMNS).eq("id", key_id).execute().data
    return _public(rows[0]) if rows else None


def revoke_key(supa, key_id: int, *, now: datetime | None = None) -> dict | None:
    """Revocation is a timestamp and it is final: re-revoking keeps the first timestamp, so
    the audit record of when the key died never moves."""
    rows = supa.table(KEYS).select("*").eq("id", key_id).execute().data
    if not rows:
        return None
    row = rows[0]
    if row.get("revoked_at"):
        return _public(row)
    at = (now or datetime.now(timezone.utc)).isoformat()
    updated = supa.table(KEYS).update({"revoked_at": at}).eq("id", key_id).execute().data
    record_event(supa, key_id, "admin/keys", "revoked", detail=row["label"])
    return _public(updated[0] if updated else {**row, "revoked_at": at})


def verify_key(supa, presented: str | None, *, now: datetime | None = None) -> dict | None:
    """The row for a live key, else None. Every failure -- malformed, unknown, revoked --
    returns None, so a caller cannot probe which keys exist. `last_used_at` is written at
    most once a minute per key (spec §1.2), never per request."""
    if not presented or not _KEY_RE.match(presented):
        return None
    digest = hash_key(presented)
    rows = supa.table(KEYS).select("*").eq("key_hash", digest).execute().data
    if not rows or not hmac.compare_digest(rows[0]["key_hash"], digest):
        return None
    row = rows[0]
    if row.get("revoked_at"):
        return None
    now = now or datetime.now(timezone.utc)
    last = row.get("last_used_at")
    stale = True
    if last:
        try:
            stale = now - datetime.fromisoformat(str(last).replace("Z", "+00:00")) >= _LAST_USED_WRITE_EVERY
        except ValueError:
            stale = True
    if stale:
        supa.table(KEYS).update({"last_used_at": now.isoformat()}).eq("id", row["id"]).execute()
        row = {**row, "last_used_at": now.isoformat()}
    return _public(row)


def record_event(supa, key_id: int, route: str, outcome: str, *, detail: str | None = None,
                 client_order_id: str | None = None) -> dict:
    """One audit row (spec §1.5). Detail stays short and never carries payloads or key material."""
    return supa.table(EVENTS).insert({
        "key_id": key_id, "route": route, "outcome": outcome,
        "at": datetime.now(timezone.utc).isoformat(),
        "detail": (detail or "")[:200] or None, "client_order_id": client_order_id,
    }).execute().data[0]


def recent_events(supa, key_id: int, limit: int = 50) -> list[dict]:
    rows = supa.table(EVENTS).select("*").eq("key_id", key_id).order("at", desc=True).execute().data
    return rows[:limit]
