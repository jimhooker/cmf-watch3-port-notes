#!/usr/bin/env python3
"""Boot stock Watch 3 Pro firmware in the emulator with the breakpoint probe attached and walk the UI:
crown press, scrolling, taps and swipes, saving a screenshot after each step. Emulator only; nothing touches a watch.

usage: scripts/emu_tour.py PATH_TO_cmf-watch-utils WORK_DIR RUN_NAME [ADDR_MAP.csv]

Output in WORK_DIR/runs/RUN_NAME: hits.csv (+ .counts), uart0.log, and shots/NN-label.png.
Input lines are the emulator's own format (emulator/hw/ats3089c.c): "t down x y" touch, "c down" crown button,
"r delta" crown rotation. The screen is 466 x 466.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def swipe(x0, y0, x1, y1, steps=24):
    pts = [(x0 + (x1 - x0) * i // steps, y0 + (y1 - y0) * i // steps) for i in range(steps + 1)]
    return ["t 1 %d %d" % p for p in pts] + ["t 0 %d %d" % pts[-1]]


def tap(x, y):
    return ["t 1 %d %d" % (x, y), "t 0 %d %d" % (x, y)]


CROWN = ["c 1", "c 0"]
GEAR = (370, 304)  # settings icon in the quick-settings panel
SCROLL = swipe(233, 380, 233, 120)        # drag the list up by about four rows
QUICK = swipe(233, 30, 233, 400)          # pull down the quick-settings panel from the face


def visit(open_steps, scrolls, row_y, label):
    """From the watch face: open a list, scroll it, tap a row, tap inside, then press the crown to leave."""
    steps = [(3, lines, "%s-%s" % (label, n)) for n, lines in open_steps]
    steps += [(2, SCROLL, "%s-scroll%d" % (label, i + 1)) for i in range(scrolls)]
    steps += [(3, tap(233, row_y), label + "-row"), (4, tap(233, 233), label + "-inner"),
              (3, swipe(233, 330, 233, 180), label + "-drag"), (3, CROWN, label + "-leave")]
    return steps


SETTINGS = [("panel", QUICK), ("open", tap(*GEAR))]
APPS = [("open", CROWN)]
# (seconds to wait before the step, input lines, label). The tour starts once the watch face is on screen.
TOUR = [(2, [], "face")]
for n, (scrolls, y) in enumerate([(0, 150), (0, 300), (1, 233), (2, 233), (3, 233)]):
    TOUR += visit(SETTINGS, scrolls, y, "set%d" % n)
for n, (scrolls, y) in enumerate([(0, 150), (1, 233), (2, 233), (3, 233)]):
    TOUR += visit(APPS, scrolls, y, "app%d" % n)
TOUR += [(3, swipe(420, 233, 60, 233), "card-left"), (3, CROWN, "home"), (3, swipe(60, 233, 420, 233), "card-right"),
         (3, CROWN, "end")]


def face_ready(frame):
    """True once the frame is mostly drawn (the boot logo and a blank panel are nearly all black)."""
    try:
        data = frame.read_bytes()
    except OSError:
        return False
    body = data[-466 * 466 * 3:]
    if len(body) < 466 * 466 * 3:
        return False
    lit = sum(1 for i in range(0, len(body), 3 * 97) if body[i] + body[i + 1] + body[i + 2] > 60)
    return lit * 97 * 3 > 0.12 * len(body)


def main():
    utils, work, name = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3]
    run = work / "runs" / name
    env = dict(os.environ)
    if len(sys.argv) > 4:
        env["ADDR_MAP"] = str(Path(sys.argv[4]).resolve())
    total = sum(step[0] + 1.5 for step in TOUR) + 90
    probe = subprocess.Popen(["bash", str(HERE / "scripts" / "emu_hits.sh"), str(utils), str(work), str(int(total)), name],
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.monotonic() + 30
    while not (run / "input.txt").exists():
        if probe.poll() is not None or time.monotonic() > deadline:
            sys.exit("emulator did not start: " + (probe.stdout.read() if probe.stdout else ""))
        time.sleep(0.2)
    shots = run / "shots"
    shots.mkdir(exist_ok=True)
    # stock boots twice (it restarts once after its first power-on); wait for the second boot, then the face
    ready = 0
    deadline = time.monotonic() + 120
    while ready < 4 and time.monotonic() < deadline:
        time.sleep(1)
        try:
            boots = (run / "uart0.log").read_bytes().count(b"*** Booting Zephyr OS")
        except OSError:
            boots = 0
        ready = ready + 1 if boots >= 2 and face_ready(run / "frame.ppm") else 0
    for n, (wait, lines, label) in enumerate(TOUR):
        time.sleep(wait)
        if lines:
            with open(run / "input.txt", "a") as f:
                f.write("\n".join(lines) + "\n")
        time.sleep(1.5)
        frame = run / "frame.ppm"
        if frame.exists():
            shutil.copyfile(frame, shots / ("%02d-%s.ppm" % (n, label)))
    print(probe.communicate()[0][-400:])
    if shutil.which("ffmpeg"):
        for ppm in sorted(shots.glob("*.ppm")):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(ppm), str(ppm.with_suffix(".png"))])
            ppm.unlink()
    print("shots in", shots)


if __name__ == "__main__":
    main()
