#!/usr/bin/env python3
"""Boot stock Watch 3 Pro firmware in the emulator, wait for the watch face, then call stock functions from the UI
thread and record the virtual motor's response. Emulator only; nothing touches a watch.

usage: scripts/emu_call.py PATH_TO_cmf-watch-utils WORK_DIR RUN_NAME ANCHOR [--dump LABEL:ADDR:LEN ...] [--poke ADDR:HEXBYTES ...] [LABEL:ADDR:R0:R1[:SECONDS] ...]

ANCHOR is a function the UI thread calls often (hex, e.g. LV_OBJ_INVALIDATE). All numbers are hex.
Output: WORK_DIR/runs/RUN_NAME/calls/calls.txt ("label ret=... ms:duty ms:duty ...") and any memory dumps.
"""
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
from emu_tour import face_ready  # noqa: E402


def main():
    utils, work, name, anchor = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3], sys.argv[4]
    dumps, pokes, calls = [], [], []
    args = sys.argv[5:]
    while args:
        a = args.pop(0)
        if a == "--dump":
            dumps.append(args.pop(0))
        elif a == "--poke":
            pokes.append(args.pop(0))
        else:
            calls.append(a)
    run = work / "runs" / name
    if run.exists():
        sys.exit("%s exists; pick another RUN_NAME" % run)
    port = int(os.environ.get("EMU_GDB_PORT", "27778"))
    seconds = int(150 + sum(float(c.split(':')[4]) + 3 if c.count(':') > 3 else 7 for c in calls))
    emu = subprocess.Popen(
        ["uv", "run", "cmf-watch-utils", "emu", "run", "--profile", "wp3-stock", "--fixtures", str(work / "fixtures-wp3"),
         "--qemu", str(work / "runtime" / "qemu-system-arm"), "--rom", str(work / "runtime" / "compat.bin"),
         "--headless", "--seconds", str(seconds), "--allow-reboot", "--watch-face-preview", "--gdb-port", str(port),
         "--output", str(run)], cwd=utils, stdout=open(work / "runs" / (name + ".emu.log"), "w"), stderr=subprocess.STDOUT,
        start_new_session=True)
    try:
        ready, deadline = 0, time.monotonic() + 120
        while ready < 4:
            if emu.poll() is not None or time.monotonic() > deadline:
                sys.exit("emulator did not reach the watch face; see %s" % (work / "runs" / (name + ".emu.log")))
            time.sleep(1)
            try:
                boots = (run / "uart0.log").read_bytes().count(b"*** Booting Zephyr OS")
            except OSError:
                boots = 0
            ready = ready + 1 if boots >= 2 and face_ready(run / "frame.ppm") else 0
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            pass
        env = dict(os.environ, EMU_GDB_PORT=str(port), EMU_ANCHOR=anchor, EMU_CALLS=";".join(calls),
                   EMU_DUMPS=";".join(dumps), EMU_POKES=";".join(pokes), EMU_MOTOR_LOG=str(run / "motor.log"), EMU_OUT=str(run / "calls"))
        gdb = os.environ.get("GDB", str(work / "gdb" / "root" / "usr" / "bin" / "gdb-multiarch"))
        out = subprocess.run([gdb, "-q", "-batch", "-x", str(HERE / "scripts" / "emu_call_gdb.py")], env=env,
                             capture_output=True, text=True, timeout=seconds + 60)
        print(out.stdout[-3000:])
        if out.returncode:
            print(out.stderr[-1500:])
    finally:
        # stop only the emulator this script started (its own process group), QEMU child included
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(emu.pid, sig)
                emu.wait(timeout=15)
                break
            except (ProcessLookupError, subprocess.TimeoutExpired):
                continue
    print("results in", run / "calls")


if __name__ == "__main__":
    main()
