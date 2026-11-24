"""Emulator only. Wait on QEMU's control port for the guest's update reboot (reset reason 0x42520002), then save
the virtual NOR, using cmf-watch-utils' own capture_reset (emu/recovery.py). The emulator wires this up for the
Watch Pro 2 only; for the Watch 3 Pro its install step takes --nor and --pending-temp instead.

usage (from the cmf-watch-utils checkout): uv run python KIT/scripts/emu_capture_ota_reset.py QMP_PORT OUT_NOR TIMEOUT_SECONDS
"""
import sys
from pathlib import Path

from cmf_watch_utils.emu.profiles import PROFILES
from cmf_watch_utils.emu.recovery import capture_reset, pending_records

port, out, timeout = int(sys.argv[1]), Path(sys.argv[2]).resolve(), float(sys.argv[3])
if out.exists():
    sys.exit("%s exists" % out)
capture_reset(port, out, PROFILES["wp3-stock"].model.nor_bytes, timeout)
print("update reboot seen; saved", out)
print("pending update records in the saved NOR:", len(list(pending_records(out.read_bytes()))))
