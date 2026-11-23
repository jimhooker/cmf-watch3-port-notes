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
#   EMU_CALLS      semicolon list of "label:addr:r0:r1[:seconds[:r2[:r3[:s0[:s1]]]]]" (hex numbers; seconds to
#                  let the guest run afterwards, decimal, default 4; s0 and s1 are the fifth and sixth arguments,
#                  passed on the stack). A value is [@]BASE(/OFF)*[+OFF]: BASE is hex or $LABEL (what the earlier
#                  call or capture LABEL gave), each /OFF replaces the address with the 32-bit word stored at
#                  address+OFF, +OFF is added without reading, and a leading @ reads the word at the result.
#                  Five entries are not calls: "label:shot" saves the screen, "label:poke:addr:value" writes a
#                  32-bit word, "label:peek:addr" reads one, "label:input:line|line...[:seconds]" sends emulator
#                  input lines, "label:wait:seconds" lets the guest run.
#   EMU_CAPTURES   optional semicolon list of "name:addr:reg": whenever addr is reached, remember reg as $name
#   EMU_FORCES     optional semicolon list of "addr:reg:value": whenever addr is reached, set reg to value
#   EMU_INPUT      the run's input.txt; EMU_FRAME the run's frame.ppm (for "input" and "shot")
#   EMU_DUMPS      optional semicolon list of "label:addr:len" memory ranges to save first (hex)
#   EMU_DUMPS_AFTER  the same, saved after the last call; addr takes the same forms as a register value
#   EMU_POKES      optional semicolon list of "addr:hexbytes" written to guest memory before the calls
#   EMU_MOTOR_LOG  the run's motor.log
#   EMU_OUT        output directory
import os
import shutil
import threading

import gdb

PORT = int(os.environ["EMU_GDB_PORT"])
ANCHOR = int(os.environ["EMU_ANCHOR"], 16) & ~1
OUT = os.environ["EMU_OUT"]
MOTOR = os.environ["EMU_MOTOR_LOG"]
CALLS = [c.split(":") for c in os.environ.get("EMU_CALLS", "").split(";") if c]
DUMPS = [c.split(":") for c in os.environ.get("EMU_DUMPS", "").split(";") if c]
POKES = [c.split(":") for c in os.environ.get("EMU_POKES", "").split(";") if c]
AFTER = [c.split(":") for c in os.environ.get("EMU_DUMPS_AFTER", "").split(";") if c]
CAPTURES = {int(a, 16) & ~1: (n, r) for n, a, r in
            (c.split(":") for c in os.environ.get("EMU_CAPTURES", "").split(";") if c)}
FORCES = {int(a, 16) & ~1: (r, int(v, 16)) for a, r, v in
          (c.split(":") for c in os.environ.get("EMU_FORCES", "").split(";") if c)}
SAVED = ("r0", "r1", "r2", "r3", "r12", "lr")
RETURNED = {}


def reg(name):
    return int(gdb.parse_and_eval("$" + name)) & 0xFFFFFFFF


def word(addr):
    return int.from_bytes(bytes(gdb.selected_inferior().read_memory(addr, 4)), "little")


def resolve(text):
    """[@]BASE(/OFF)*[+OFF]: BASE is a hex number or $LABEL (what the earlier call or capture LABEL gave); each
    /OFF replaces the address with the 32-bit word stored at address+OFF right now; +OFF is added without
    reading; a leading @ reads the word at the result."""
    path, _, offset = text.lstrip("@").partition("+")
    steps = path.split("/")
    number = RETURNED[steps[0][1:]] if steps[0].startswith("$") else int(steps[0], 16)
    for step in steps[1:]:
        number = word(number + int(step, 16))
    number += int(offset, 16) if offset else 0
    return word(number) if text.startswith("@") else number


def save(label, addr, length):
    data = bytes(gdb.selected_inferior().read_memory(resolve(addr), int(length, 16)))
    with open(os.path.join(OUT, label + ".bin"), "wb") as f:
        f.write(data)


def motor_lines():
    try:
        with open(MOTOR) as f:
            return [tuple(int(x) for x in line.split()) for line in f if line.strip()]
    except OSError:
        return []


def resume():
    """Let the guest run until it stops, noting captures and applying forces. Returns where it stopped."""
    gdb.execute("continue", to_string=True)
    pc = reg("pc") & ~1
    if pc in CAPTURES:
        name, register = CAPTURES[pc]
        RETURNED[name] = reg(register)
    if pc in FORCES:
        register, value = FORCES[pc]
        gdb.execute("set $%s = %d" % (register, value))
    return pc


def run_to_anchor():
    while resume() != ANCHOR:
        pass


def free_run(seconds):
    """Let the guest run at full speed for a while (anchor breakpoint off), then stop it again."""
    anchor_bp.enabled = False
    fired = threading.Event()

    def stop():
        fired.set()
        gdb.execute("interrupt")

    timer = threading.Timer(seconds, lambda: gdb.post_event(stop))
    timer.start()
    try:
        while not fired.is_set():
            resume()
    finally:
        timer.cancel()
        anchor_bp.enabled = True


gdb.execute("set pagination off")
gdb.execute("set confirm off")
gdb.execute("set architecture armv8-m.main")
gdb.execute("target remote 127.0.0.1:%d" % PORT)
os.makedirs(OUT, exist_ok=True)
for label, addr, length in DUMPS:
    save(label, addr, length)
for addr, data in POKES:
    gdb.selected_inferior().write_memory(int(addr, 16), bytes.fromhex(data))
anchor_bp = gdb.Breakpoint("*0x%x" % ANCHOR, internal=True)
for stop_addr in set(CAPTURES) | set(FORCES):
    gdb.Breakpoint("*0x%x" % stop_addr, internal=True)
def finish():
    for label, addr, length in AFTER:
        try:
            save(label, addr, length)
        except (gdb.error, KeyError) as error:
            print("dump %s failed: %s" % (label, error))
    with open(os.path.join(OUT, "calls.txt"), "w") as f:
        for label, ret, lines in results:
            f.write("%s ret=%#x %s\n" % (label, ret, " ".join("%d:%d" % (t, duty) for t, duty, _ in lines)))


results = []
try:
    for call in CALLS:
        label, addr = call[:2]
        if addr == "shot":
            shutil.copyfile(os.environ["EMU_FRAME"], os.path.join(OUT, label + ".ppm"))
            results.append((label, 0, []))
            continue
        if addr == "poke":
            where, value = resolve(call[2]), resolve(call[3])
            gdb.selected_inferior().write_memory(where, value.to_bytes(4, "little"))
            results.append((label, where, []))
            print("%s wrote %#x to %#x" % (label, value, where))
            continue
        if addr == "input":
            before = len(motor_lines())
            with open(os.environ["EMU_INPUT"], "a") as f:
                f.write(call[2].replace("|", "\n") + "\n")
            free_run(float(call[3]) if len(call) > 3 else 3.0)
            results.append((label, 0, motor_lines()[before:]))
            print("%s ret=0x0 motor=%s" % (label, results[-1][2]))
            continue
        if addr == "wait":
            before = len(motor_lines())
            free_run(float(call[2]))
            results.append((label, 0, motor_lines()[before:]))
            print("%s ret=0x0 motor=%s" % (label, results[-1][2]))
            continue
        if addr == "peek":
            try:
                results.append((label, word(resolve(call[2])), []))
            except gdb.MemoryError:
                results.append((label, 0xFFFFFFFF, []))  # the path ran into unmapped memory
            print("%s ret=%#x" % (label, results[-1][1]))
            continue
        r0, r1 = call[2:4]
        wait = float(call[4]) if len(call) > 4 else 4.0
        run_to_anchor()
        saved = {name: reg(name) for name in SAVED}
        sp = reg("sp")
        before = len(motor_lines())
        for name, text in zip(("r0", "r1", "r2", "r3"), [r0, r1] + call[5:7]):
            gdb.execute("set $%s = %d" % (name, resolve(text)))
        stack = b"".join(resolve(text).to_bytes(4, "little") for text in call[7:9])
        called_sp = sp - 8 if stack else sp
        if stack:
            gdb.selected_inferior().write_memory(called_sp, stack.ljust(8, b"\0"))
            gdb.execute("set $sp = %d" % called_sp)
        gdb.execute("set $lr = %d" % (ANCHOR | 1))
        gdb.execute("set $pc = %d" % (int(addr, 16) & ~1))
        while True:
            run_to_anchor()
            if reg("sp") == called_sp:
                break
        ret = RETURNED[label] = reg("r0")
        gdb.execute("set $sp = %d" % sp)
        for name, value in saved.items():
            gdb.execute("set $%s = %d" % (name, value))
        free_run(wait)
        lines = motor_lines()[before:]
        results.append((label, ret, lines))
        print("%s ret=%#x motor=%s" % (label, ret, lines))
finally:
    finish()  # keep what was recorded even when a step fails or the guest stops
gdb.execute("detach")
