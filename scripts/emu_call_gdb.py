# Runs inside gdb, attached to a booted emulator. Calls stock functions from the UI thread and records what the
# virtual motor does after each call. Emulator only; nothing touches a watch.
#
# How a call is made: wait for the UI thread to enter ANCHOR, save its registers, point pc at the target with lr
# set back to ANCHOR, let it run until it returns there, then restore the registers so the interrupted call
# carries on as if nothing happened.
#
# Environment:
#   EMU_GDB_PORT   gdb port of the emulator
#   EMU_ANCHOR     address of a function the UI thread calls often (hex)
#   EMU_CALLS      semicolon list of "label:addr:r0:r1[:seconds]" (hex numbers; seconds to let the guest run
#                  afterwards, decimal, default 4)
#   EMU_DUMPS      optional semicolon list of "label:addr:len" memory ranges to save first (hex)
#   EMU_POKES      optional semicolon list of "addr:hexbytes" written to guest memory before the calls
#   EMU_MOTOR_LOG  the run's motor.log
#   EMU_OUT        output directory
import os
import threading

import gdb

PORT = int(os.environ["EMU_GDB_PORT"])
ANCHOR = int(os.environ["EMU_ANCHOR"], 16) & ~1
OUT = os.environ["EMU_OUT"]
MOTOR = os.environ["EMU_MOTOR_LOG"]
CALLS = [c.split(":") for c in os.environ.get("EMU_CALLS", "").split(";") if c]
DUMPS = [c.split(":") for c in os.environ.get("EMU_DUMPS", "").split(";") if c]
POKES = [c.split(":") for c in os.environ.get("EMU_POKES", "").split(";") if c]
SAVED = ("r0", "r1", "r2", "r3", "r12", "lr")


def reg(name):
    return int(gdb.parse_and_eval("$" + name)) & 0xFFFFFFFF


def motor_lines():
    try:
        with open(MOTOR) as f:
            return [tuple(int(x) for x in line.split()) for line in f if line.strip()]
    except OSError:
        return []


def run_to_anchor():
    while True:
        gdb.execute("continue", to_string=True)
        if (reg("pc") & ~1) == ANCHOR:
            return


def free_run(seconds):
    """Let the guest run at full speed for a while (anchor breakpoint off), then stop it again."""
    anchor_bp.enabled = False
    timer = threading.Timer(seconds, lambda: gdb.post_event(lambda: gdb.execute("interrupt")))
    timer.start()
    try:
        gdb.execute("continue", to_string=True)
    finally:
        timer.cancel()
        anchor_bp.enabled = True


gdb.execute("set pagination off")
gdb.execute("set confirm off")
gdb.execute("set architecture armv8-m.main")
gdb.execute("target remote 127.0.0.1:%d" % PORT)
os.makedirs(OUT, exist_ok=True)
for label, addr, length in DUMPS:
    data = bytes(gdb.selected_inferior().read_memory(int(addr, 16), int(length, 16)))
    with open(os.path.join(OUT, label + ".bin"), "wb") as f:
        f.write(data)
for addr, data in POKES:
    gdb.selected_inferior().write_memory(int(addr, 16), bytes.fromhex(data))
anchor_bp = gdb.Breakpoint("*0x%x" % ANCHOR, internal=True)
results = []
for call in CALLS:
    label, addr, r0, r1 = call[:4]
    wait = float(call[4]) if len(call) > 4 else 4.0
    run_to_anchor()
    saved = {name: reg(name) for name in SAVED}
    sp = reg("sp")
    before = len(motor_lines())
    gdb.execute("set $r0 = %d" % int(r0, 16))
    gdb.execute("set $r1 = %d" % int(r1, 16))
    gdb.execute("set $lr = %d" % (ANCHOR | 1))
    gdb.execute("set $pc = %d" % (int(addr, 16) & ~1))
    while True:
        run_to_anchor()
        if reg("sp") == sp:
            break
    ret = reg("r0")
    for name, value in saved.items():
        gdb.execute("set $%s = %d" % (name, value))
    free_run(wait)
    lines = motor_lines()[before:]
    results.append((label, ret, lines))
    print("%s ret=%#x motor=%s" % (label, ret, lines))
with open(os.path.join(OUT, "calls.txt"), "w") as f:
    for label, ret, lines in results:
        f.write("%s ret=%#x %s\n" % (label, ret, " ".join("%d:%d" % (t, duty) for t, duty, _ in lines)))
gdb.execute("detach")
