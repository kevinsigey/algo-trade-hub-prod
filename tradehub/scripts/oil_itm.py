"""Freeze + grade the hour's ITM line pick. Run every ~10 minutes by cron:
docker exec stack-tradehub-1 python -m tradehub.scripts.oil_itm"""

from __future__ import annotations

from tradehub.core.supabase_client import get_client
from tradehub.oil_itm import run


def main() -> None:
    print(run(get_client()))


if __name__ == "__main__":
    main()
