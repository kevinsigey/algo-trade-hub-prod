"""guidance_filings reads and writes."""

from __future__ import annotations

FILINGS = "guidance_filings"


def known_accessions(supa) -> set[str]:
    return {r["accession"] for r in supa.table(FILINGS).select("accession").execute().data}


def add_filing(supa, row: dict) -> None:
    supa.table(FILINGS).insert({**row, "status": "new"}).execute()
