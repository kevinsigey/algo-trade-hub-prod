"""Every table a migration creates must end up with RLS on (deep dive 2026-11-03: three tables shipped without it,
with the anon role holding full grants and the anon key public). Tables from the first schema are checked too."""
from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "market_sentiment_tool" / "supabase" / "migrations"
CREATE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?\"?(\w+)\"?", re.I)
ENABLE = re.compile(r"alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?(?:public\.)?\"?(\w+)\"?\s+enable\s+row\s+level\s+security", re.I)


def test_every_created_table_enables_rls():
    created, enabled = set(), set()
    for path in sorted(MIGRATIONS.glob("*.sql")):
        text = re.sub(r"--[^\n]*", "", path.read_text())
        created |= {m.lower() for m in CREATE.findall(text)}
        enabled |= {m.lower() for m in ENABLE.findall(text)}
    assert created - enabled == set()
