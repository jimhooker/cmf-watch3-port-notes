#!/usr/bin/env python3
"""Boot stock Watch 3 Pro firmware in the emulator, wait for the watch face, then call stock functions from the UI
thread and record the virtual motor's response. Emulator only; nothing touches a watch.

usage: scripts/emu_call.py PATH_TO_cmf-watch-utils WORK_DIR RUN_NAME ANCHOR [--dump LABEL:ADDR:LEN ...]
           [--poke ADDR:HEXBYTES ...] [--dump-after LABEL:ADDR:LEN ...] [--capture NAME:ADDR:REG ...]
           [--force ADDR:REG:VALUE ...] [STEP ...]

STEP is one of
  LABEL:ADDR:R0:R1[:SECONDS[:R2[:R3[:S0[:S1]]]]]   call ADDR; S0 and S1 are the fifth and sixth arguments (stack)
  LABEL:shot                                       save the screen as calls/LABEL.png
  LABEL:poke:ADDR:VALUE                            write the 32-bit VALUE at ADDR
  LABEL:input:WHAT[:SECONDS]                       send input: "crown", "tap X Y", "swipe X0 Y0 X1 Y1" or a raw
                                                   emulator input line; then let the guest run (default 3 s)
  LABEL:wait:SECONDS                               let the guest run
  LABEL:peek:ADDR                                  read the 32-bit word at ADDR (reported as the step's ret)

ANCHOR is a function the UI thread calls often (hex, e.g. LV_OBJ_INVALIDATE, or the LVGL timer handler when the
screen may be idle). All numbers are hex, except SECONDS (decimal: how long the guest runs after the call,
default 4) and the coordinates of an input. A value (register, stack argument, poke, --dump-after address) is
[@]BASE(/OFF)*[+OFF]: BASE is hex or $LABEL (what the earlier call LABEL returned, or what --capture NAME saw);
each /OFF replaces the address with the 32-bit word stored at address+OFF at that moment; +OFF is added without
reading; a leading @ reads the word at the result. So a call can allocate a buffer and later calls can use it:
  'buf:ALLOC:...'  'find:ADDR:$buf:...'  'use:ADDR:@$buf:0:1:$buf+10'  --dump-after 'out:$buf:40'
and '$view/14/4' is *(*(view+0x14)+4).
--capture remembers register REG as $NAME whenever the guest reaches ADDR; --force sets REG to VALUE there.
--dump ranges are saved before the calls, --dump-after ranges once all calls have returned.
Output: WORK_DIR/runs/RUN_NAME/calls/calls.txt ("label ret=... ms:duty ms:duty ...") and any memory dumps.
Set EMU_APP=path/to/app.bin to boot a modified app image instead of the stock one.
"""
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
from emu_launch import command  # noqa: E402
from emu_tour import CROWN, face_ready, swipe, tap  # noqa: E402


def step(text):
    """One STEP as the gdb side wants it, and roughly how many seconds it takes."""
    fields = text.split(":")
    if fields[1] in ("shot", "poke", "peek"):
        return text, 1.0
    if fields[1] == "wait":
        return text, float(fields[2]) + 1
    if fields[1] == "input":
        words = fields[2].split()
        lines = (CROWN if words[0] == "crown" else tap(int(words[1]), int(words[2])) if words[0] == "tap"
                 else swipe(*(int(n) for n in words[1:5])) if words[0] == "swipe" else [fields[2]])
        wait = fields[3] if len(fields) > 3 else "3"
        return ":".join([fields[0], "input", "|".join(lines), wait]), float(wait) + 1
    return text, (float(fields[4]) + 3 if len(fields) > 4 else 7.0)


def main():
    utils, work, name, anchor = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3], sys.argv[4]
    dumps, pokes, after, captures, forces, calls = [], [], [], [], [], []
    lists = {"--dump": dumps, "--poke": pokes, "--dump-after": after, "--capture": captures, "--force": forces}
    args = sys.argv[5:]
    while args:
        a = args.pop(0)
        if a in lists:
            lists[a].append(args.pop(0))
        else:
            calls.append(step(a))
    run = work / "runs" / name
    if run.exists():
        sys.exit("%s exists; pick another RUN_NAME" % run)
    port = int(os.environ.get("EMU_GDB_PORT", "27778"))
    seconds = int(150 + sum(cost for _, cost in calls))
    emu = subprocess.Popen(command(utils, work, run, port, seconds), cwd=utils,
                           stdout=open(work / "runs" / (name + ".emu.log"), "w"), stderr=subprocess.STDOUT,
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
        env = dict(os.environ, EMU_GDB_PORT=str(port), EMU_ANCHOR=anchor, EMU_CALLS=";".join(c for c, _ in calls),
                   EMU_DUMPS=";".join(dumps), EMU_POKES=";".join(pokes), EMU_CAPTURES=";".join(captures),
                   EMU_FORCES=";".join(forces), EMU_INPUT=str(run / "input.txt"), EMU_FRAME=str(run / "frame.ppm"),
                   EMU_DUMPS_AFTER=";".join(after), EMU_MOTOR_LOG=str(run / "motor.log"), EMU_OUT=str(run / "calls"))
        gdb = os.environ.get("GDB", str(work / "gdb" / "root" / "usr" / "bin" / "gdb-multiarch"))
        out = subprocess.run([gdb, "-q", "-batch", "-x", str(HERE / "scripts" / "emu_call_gdb.py")], env=env,
                             capture_output=True, text=True, timeout=seconds + 60)
        (work / "runs" / (name + ".gdb.log")).write_text(out.stdout + out.stderr)
        print("\n".join(line for line in out.stdout.splitlines() if " ret=" in line or " wrote " in line))
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
    if shutil.which("ffmpeg"):
        for ppm in sorted((run / "calls").glob("*.ppm")):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(ppm), str(ppm.with_suffix(".png"))])
            ppm.unlink()
    print("results in", run / "calls")


if __name__ == "__main__":
    main()
