"""The one SEC User-Agent builder.

SEC fair access requires a declared contact in the User-Agent of
every request to sec.gov. The contact is environment configuration
(SEC_CONTACT_EMAIL, set in /opt/stack/.env and forwarded by compose),
never a literal in code, and every SEC fetch in the hub builds its
header here so the rule has exactly one home. An unset or blank
contact is a hard failure at fetch time: a request that cannot
declare its contact does not go out (Claude's #559 fix round,
2026-11-18 -- previously two modules hardcoded the address and the
screening layer silently degraded to a bare placeholder).
"""

from __future__ import annotations

import os


def sec_user_agent() -> dict:
    email = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
    if not email:
        raise RuntimeError(
            "SEC_CONTACT_EMAIL is not set: SEC fair access requires a "
            "User-Agent carrying a contact email, so no SEC request "
            "goes out until it is configured")
    return {"User-Agent": f"algo-trade-hub research {email}"}
