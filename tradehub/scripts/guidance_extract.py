"""Cron entrypoint: extract guidance from new SEC earnings releases.

Mirrors the shape of tradehub/scripts/fifteen_min_run.py.
"""

from __future__ import annotations

import json
import os
import sys

import httpx

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.guidance.extract import ask_model, consensus, run


def _fetch_html(url: str) -> str:
    """Fetch HTML from a URL with SEC-compliant User-Agent."""
    ua = os.getenv("SEC_USER_AGENT", "AlgoTradeHub research hub-research@example.com")
    with httpx.Client(timeout=20) as client:
        resp = client.get(url, headers={"User-Agent": ua})
        resp.raise_for_status()
        return resp.text


def main() -> int:
    load_local_env()
    key = os.getenv("OPENROUTER_API_KEY", "")
    summary = run(
        get_client(),
        fetch=_fetch_html,
        model=ask_model,
        consensus=consensus,
        key=key,
    )
    print(json.dumps(summary, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())