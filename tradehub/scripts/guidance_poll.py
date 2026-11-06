"""Cron entrypoint: record new earnings-release 8-Ks (item 2.02) for the S&P 100 as `new` guidance_filings."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.guidance.edgar import SecRefused, earnings_filings, exhibit_url
from tradehub.guidance.store import add_filing, known_accessions
from tradehub.guidance.universe import UNIVERSE


def run(supa, now: datetime, *, filings=earnings_filings, exhibit=exhibit_url) -> dict[str, Any]:
    known = known_accessions(supa)
    since = (now - timedelta(days=10)).date()
    out: dict[str, Any] = {"checked": 0, "added": 0}
    try:
        for ticker, cik in UNIVERSE.items():
            out["checked"] += 1
            for f in filings(cik, since=since):
                if f["accession"] in known:
                    continue
                add_filing(supa, {**f, "ticker": ticker, "doc_url": exhibit(cik, f["accession"])})
                known.add(f["accession"])
                out["added"] += 1
    except SecRefused as e:
        out.update(stopped="sec refused", error=str(e))
    return out


def main() -> int:
    load_local_env()
    print(json.dumps(run(get_client(), datetime.now(UTC)), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
