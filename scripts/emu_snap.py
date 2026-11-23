#!/usr/bin/env python3
"""Boot stock Watch 3 Pro firmware in the emulator, script some input, and save memory when chosen functions are
entered or return. Emulator only; nothing touches a watch.

usage: scripts/emu_snap.py PATH_TO_cmf-watch-utils WORK_DIR RUN_NAME [OPTION ...]

  --at LABEL:ADDR[:ret]        stop when ADDR is reached (hex). With ":ret" the memory is saved when that function
                               returns to its caller instead of on entry.
  --save LABEL:NAME:PATH:LEN   at stop LABEL, save LEN bytes (hex) found at PATH as snap/LABEL-<hit>-NAME.bin.
                               PATH is BASE(/OFF)*[+OFF|-OFF]: BASE is r0..r3 (as they were on entry), "ret" (r0 at
                               return) or a hex address; each /OFF replaces the address with the 32-bit word stored
                               at address+OFF; a final +OFF or -OFF is added without reading. "r0/14/4" is
                               *(*(r0+0x14)+4).
  --force ADDR:REG:VALUE       whenever ADDR is reached, set register REG to VALUE (hex) and carry on.
  --input SECONDS:WHAT         SECONDS after the watch face appears (decimal), send input. WHAT is "crown",
                               "tap X Y", "swipe X0 Y0 X1 Y1" or a raw emulator input line ("t 1 x y", "c 1",
                               "r delta"). The screen is 466 x 466.
  --shot SECONDS:NAME          SECONDS after the watch face appears, save the screen as snap/NAME.png.
  --max-hits N                 stops recorded per LABEL (default 2).

Output in WORK_DIR/runs/RUN_NAME/snap: stops.txt (one line per stop with the registers), the .bin dumps and shots.
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


def input_lines(what):
    words = what.split()
    if words[0] == "crown":
        return CROWN
    if words[0] == "tap":
        return tap(int(words[1]), int(words[2]))
    if words[0] == "swipe":
        return swipe(*(int(n) for n in words[1:5]))
    return [what]


def main():
    utils, work, name = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3]
    options = {"--at": [], "--save": [], "--force": [], "--input": [], "--shot": [], "--max-hits": []}
    args = sys.argv[4:]
    while args:
        key = args.pop(0)
        if key not in options or not args:
            sys.exit(__doc__)
        options[key].append(args.pop(0))
    events = [(float(item.split(":", 1)[0]), "input", item.split(":", 1)[1]) for item in options["--input"]]
    events += [(float(item.split(":", 1)[0]), "shot", item.split(":", 1)[1]) for item in options["--shot"]]
    events.sort(key=lambda event: event[0])
    run = work / "runs" / name
    if run.exists():
        sys.exit("%s exists; pick another RUN_NAME" % run)
    port = int(os.environ.get("EMU_GDB_PORT", "27779"))
    last = events[-1][0] if events else 0
    log = work / "runs" / (name + ".emu.log")
    emu = subprocess.Popen(command(utils, work, run, port, int(last + 240)), cwd=utils, stdout=open(log, "w"),
                           stderr=subprocess.STDOUT, start_new_session=True)
    gdb = None
    try:
        ready, deadline = 0, time.monotonic() + 120
        while ready < 4:
            if emu.poll() is not None or time.monotonic() > deadline:
                sys.exit("emulator did not reach the watch face; see %s" % log)
            time.sleep(1)
            try:
                boots = (run / "uart0.log").read_bytes().count(b"*** Booting Zephyr OS")
            except OSError:
                boots = 0
            ready = ready + 1 if boots >= 2 and face_ready(run / "frame.ppm") else 0
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            pass
        snap = run / "snap"
        snap.mkdir(exist_ok=True)
        env = dict(os.environ, EMU_GDB_PORT=str(port), EMU_OUT=str(snap), EMU_STOPS=";".join(options["--at"]),
                   EMU_SAVES=";".join(options["--save"]), EMU_FORCES=";".join(options["--force"]),
                   EMU_MAX_HITS=(options["--max-hits"] or ["2"])[-1])
        gdb_path = os.environ.get("GDB", str(work / "gdb" / "root" / "usr" / "bin" / "gdb-multiarch"))
        gdb = subprocess.Popen([gdb_path, "-q", "-batch", "-x", str(HERE / "scripts" / "emu_snap_gdb.py")], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        time.sleep(3)  # let gdb attach and set its breakpoints
        start = time.monotonic()
        for at, kind, what in events:
            time.sleep(max(0.0, start + at - time.monotonic()))
            if kind == "input":
                with open(run / "input.txt", "a") as f:
                    f.write("\n".join(input_lines(what)) + "\n")
            elif (run / "frame.ppm").exists():
                shutil.copyfile(run / "frame.ppm", snap / (what + ".ppm"))
        time.sleep(4)
    finally:
        # stop only the emulator this script started (its own process group), QEMU child included; gdb then sees
        # the connection close, writes its results and exits
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(emu.pid, sig)
                emu.wait(timeout=15)
                break
            except (ProcessLookupError, subprocess.TimeoutExpired):
                continue
        if gdb is not None:
            try:
                print(gdb.communicate(timeout=30)[0][-3000:])
            except subprocess.TimeoutExpired:
                gdb.kill()
    if shutil.which("ffmpeg"):
        for ppm in sorted((run / "snap").glob("*.ppm")):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(ppm), str(ppm.with_suffix(".png"))])
            ppm.unlink()
    print("results in", run / "snap")


if __name__ == "__main__":
    main()
