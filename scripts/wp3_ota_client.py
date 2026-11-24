#!/usr/bin/env python3
"""cmf-watch-utils' stock update client with one change: a notification that repeats the previous one byte for
byte within WINDOW seconds is dropped, whichever of the client's two subscribed characteristics it came on.

Why: on the Linux machine used (BlueZ, bleak) every notification from a real Watch 3 Pro arrives twice, a few milliseconds apart (seen in
the pairing frames, the first AT reply and every 0xA042 data request on 2026-11-24). The upstream client answers
both copies, so the watch receives each range twice, re-requests it about 1.5 s later and finally rejects the
transfer with 0xA041 00. The watch's own re-requests come more than a second apart and still get answered.

usage, from the cmf-watch-utils checkout:
  uv run python KIT/scripts/wp3_ota_client.py physical ARGS...   # tools/ota_client.py's arguments
  uv run python KIT/scripts/wp3_ota_client.py emu ARGS...        # `cmf-watch-utils emu ...` arguments
Environment, for emulator tests only: WP3_DUP_INJECT=1 delivers every notification twice (to reproduce the real
watch), WP3_DEDUPE=0 turns the fix off. Each run prints how many repeats were dropped.
"""
import atexit
import os
import sys
import time

from cmf_watch_utils import ota_client

WINDOW = 0.2
INJECT = os.environ.get("WP3_DUP_INJECT") == "1"
DEDUPE = os.environ.get("WP3_DEDUPE", "1") != "0"
stats = {"received": 0, "dropped": 0}
_on_notify = ota_client.Ota.on_notify


def deduped(self, sender, data):
    data = bytes(data)
    stats["received"] += 1
    key, now = data, time.monotonic()
    last = getattr(self, "_wp3_last", None)
    if DEDUPE and last and last[0] == key and now - last[1] < WINDOW:
        stats["dropped"] += 1
        return
    self._wp3_last = (key, now)
    _on_notify(self, sender, data)


def injected(self, sender, data):
    deduped(self, sender, data)
    if INJECT:
        deduped(self, sender, data)


ota_client.Ota.on_notify = injected
atexit.register(lambda: print("notifications: %(received)d received, %(dropped)d dropped as repeats" % stats,
                              "(inject=%d dedupe=%d)" % (INJECT, DEDUPE), flush=True))

if __name__ == "__main__":
    mode, sys.argv = sys.argv[1], [sys.argv[0]] + sys.argv[2:]
    if mode == "physical":
        ota_client.main()
    elif mode == "emu":
        from cmf_watch_utils import cli
        sys.exit(cli.main(["emu"] + sys.argv[1:]))
    else:
        sys.exit("mode must be physical or emu")
