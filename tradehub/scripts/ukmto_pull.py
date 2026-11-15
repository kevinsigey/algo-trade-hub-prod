"""UKMTO incident pull: refresh the reported-incident layer the Oil
page reads (tradehub/geo/ukmto.py). The API is a rolling window of
recent incidents, so an hourly pull is generous; a failed pull leaves
the last good file in place -- the reader stamps its pull time either
way. Run by cron in the container:

    python -m tradehub.scripts.ukmto_pull
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from tradehub.geo import ukmto


def main() -> None:
    path = ukmto.store_path()
    try:
        rows = ukmto.fetch_incidents()
    except ukmto.UkmtoError as exc:
        print(f"ukmto_pull: {exc}; keeping the last good pull at {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"pulled_at": datetime.now(UTC).isoformat(timespec="seconds"),
                          "incidents": rows})
    # Atomic write: serialize beside the target and os.replace it over, so
    # a reader never sees partial JSON and a crashed pull never destroys
    # the last good cache.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
    print(f"ukmto_pull: wrote {path} ({len(rows)} incidents, "
          f"newest {rows[0]['date'] if rows else 'none'})")


if __name__ == "__main__":
    main()
