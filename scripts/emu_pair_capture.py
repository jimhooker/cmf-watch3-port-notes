"""Emulator only. Same steps as cmf-watch-utils `emu pair-fixture` (give the virtual watch a random test
secret over the simulated radio, then save its virtual NOR), but keep the raw capture so it can be compared
with the fixture NOR instead of being discarded on a mismatch.

usage (from the cmf-watch-utils checkout): uv run python KIT/scripts/emu_pair_capture.py HCI_PORT QMP_PORT OUT_NOR
"""
import asyncio
import socket
import sys
from pathlib import Path

from cmf_watch_utils.emu.pairing import provision
from cmf_watch_utils.emu.profiles import PROFILES
from cmf_watch_utils.emu.vm import Qmp

hci_port, qmp_port, out = int(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3]).resolve()
if out.exists():
    sys.exit("%s exists" % out)
model = PROFILES["wp3-stock"].model
with socket.create_connection(("127.0.0.1", qmp_port), timeout=10) as conn:
    with conn.makefile("rwb", buffering=0) as stream:
        qmp = Qmp(stream)
        asyncio.run(provision(hci_port, "cmf"))
        print("virtual watch kept the test secret")
        qmp.request("stop")
        qmp.request("pmemsave", val=0x11000000, size=model.nor_bytes, filename=str(out))
        qmp.quit()
print("saved", out, out.stat().st_size, "bytes")
