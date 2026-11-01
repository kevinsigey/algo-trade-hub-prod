"""Kevin-only routes. The check runs on the server: a Supabase session JWT whose user email equals
TRADEHUB_ADMIN_EMAIL. Unset email, bad token, other user: 401. It fails closed."""

from __future__ import annotations

import os

from fastapi import Depends, Header, HTTPException

from tradehub.api.dependencies import get_supabase


def require_admin(authorization: str | None = Header(None), supabase=Depends(get_supabase)) -> dict:
    admin = os.getenv("TRADEHUB_ADMIN_EMAIL", "").strip().lower()
    scheme, _, token = (authorization or "").partition(" ")
    if not admin or scheme.lower() != "bearer" or not token or supabase is None:
        raise HTTPException(status_code=401, detail="admin only")
    try:
        email = (supabase.auth.get_user(token).user.email or "").lower()
    except Exception:  # noqa: BLE001 -- expired, forged or revoked: all the same answer
        raise HTTPException(status_code=401, detail="admin only") from None
    if email != admin:
        raise HTTPException(status_code=401, detail="admin only")
    return {"email": email}
