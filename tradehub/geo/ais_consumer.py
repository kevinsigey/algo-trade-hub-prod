"""The Hormuz AIS consumer: one AISStream websocket, aggregated state only.

Generalised from the Kozmino coverage probe (Nov 2, 2026): subscribe to the
region's box union for PositionReport + ShipStaticData, keep the rolling
state in AisState, and write it to the state file every minute. The raw
firehose is NEVER stored. Single instance via an flock in the state module's
directory; the deploy crontab watcher restarts it after container recreates,
exactly like the probe.

Run: python -m tradehub.geo.ais_consumer --region hormuz \
       --key-file /cache/chokepoints-probe/key.txt \
       --state /cache/chokepoints/hormuz-state.json
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
from datetime import UTC, datetime

import websockets

from tradehub.geo.ais_state import AisState
from tradehub.geo.regions import REGIONS

STREAM = "wss://stream.aisstream.io/v0/stream"


async def run(region, key: str, state_path: str) -> None:
    state = AisState(region)
    if os.path.exists(state_path):
        try:
            state = AisState.from_json(region, open(state_path).read())
        except (ValueError, OSError):
            pass
    boxes = [[[b[0], b[1]], [b[2], b[3]]] for b in region.ais_boxes]
    backoff = 5
    while True:
        try:
            async with websockets.connect(STREAM, max_size=2**22) as ws:
                await ws.send(json.dumps({
                    "APIKey": key, "BoundingBoxes": boxes,
                    "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
                }))
                backoff = 5
                last_flush = asyncio.get_event_loop().time()
                last_tick = last_flush
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except TimeoutError:
                        raw = None
                    now = datetime.now(UTC)
                    tick = asyncio.get_event_loop().time()
                    state.note_connected(now, min(tick - last_tick, 10))
                    last_tick = tick
                    if raw is not None:
                        try:
                            state.apply(json.loads(raw), now)
                        except (ValueError, KeyError, TypeError):
                            pass  # one malformed frame never kills the feed
                    if tick - last_flush >= 60:
                        tmp = state_path + ".tmp"
                        with open(tmp, "w") as fh:
                            fh.write(state.to_json())
                        os.replace(tmp, state_path)
                        last_flush = tick
        except Exception:  # noqa: BLE001 -- reconnect forever; gaps show in connected_s
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="hormuz")
    ap.add_argument("--key-file", required=True)
    ap.add_argument("--state", required=True)
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.state), exist_ok=True)
    lock = open(os.path.join(os.path.dirname(args.state), "ais-consumer.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0  # another consumer already holds this region
    key = open(args.key_file).read().strip()
    asyncio.run(run(REGIONS[args.region], key, args.state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
