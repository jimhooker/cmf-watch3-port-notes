# Runs inside gdb, attached to a booted emulator. Stops at chosen addresses, saves memory there or when the
# function returns, and can overwrite a register at an address. Emulator only; nothing touches a watch.
#
# Environment:
#   EMU_GDB_PORT  gdb port of the emulator
#   EMU_OUT       output directory
#   EMU_STOPS     semicolon list of "label:addr[:ret]" (hex address; ":ret" saves when the function returns)
#   EMU_SAVES     semicolon list of "label:name:path:len"; path is BASE(/OFF)*[+OFF|-OFF], see emu_snap.py
#   EMU_FORCES    semicolon list of "addr:reg:value": set the register whenever addr is reached
#   EMU_MAX_HITS  stops recorded per label (default 2)
import os

import gdb

PORT = int(os.environ["EMU_GDB_PORT"])
OUT = os.environ["EMU_OUT"]
MAX_HITS = int(os.environ.get("EMU_MAX_HITS", "2"))
STOPS = [s.split(":") for s in os.environ.get("EMU_STOPS", "").split(";") if s]
SAVES = [s.split(":") for s in os.environ.get("EMU_SAVES", "").split(";") if s]
FORCES = [s.split(":") for s in os.environ.get("EMU_FORCES", "").split(";") if s]


def reg(name):
    return int(gdb.parse_and_eval("$" + name)) & 0xFFFFFFFF


def word(addr):
    return int.from_bytes(bytes(gdb.selected_inferior().read_memory(addr, 4)), "little")


def follow(path, regs):
    """Resolve BASE(/OFF)*[+OFF|-OFF] to an address; regs holds r0..r3 from entry and, after a return, ret."""
    sign = -1 if "-" in path else 1
    path, _, tail = path.replace("-", "+").partition("+")
    steps = path.split("/")
    addr = regs[steps[0]] if steps[0] in regs else int(steps[0], 16)
    for off in steps[1:]:
        addr = word(addr + int(off, 16))
    return addr + sign * (int(tail, 16) if tail else 0)


def save_all(label, hit, regs, lines):
    for save_label, name, path, length in SAVES:
        if save_label != label:
            continue
        try:
            addr = follow(path, regs)
            data = bytes(gdb.selected_inferior().read_memory(addr, int(length, 16)))
        except (gdb.MemoryError, KeyError, ValueError) as error:
            lines.append("%s %d %s: failed (%s)" % (label, hit, name, error))
            continue
        with open(os.path.join(OUT, "%s-%d-%s.bin" % (label, hit, name)), "wb") as f:
            f.write(data)
        lines.append("%s %d %s: %s = 0x%08x, %d bytes" % (label, hit, name, path, addr, len(data)))


gdb.execute("set pagination off")
gdb.execute("set confirm off")
gdb.execute("set architecture armv8-m.main")
gdb.execute("target remote 127.0.0.1:%d" % PORT)
os.makedirs(OUT, exist_ok=True)

entries, forces, pending, hits, lines = {}, {}, [], {}, []
for stop in STOPS:
    label, addr = stop[0], int(stop[1], 16) & ~1
    entries[addr] = (label, len(stop) > 2 and stop[2] == "ret", gdb.Breakpoint("*0x%x" % addr, internal=True))
    hits[label] = 0
for addr, name, value in FORCES:
    forces[int(addr, 16) & ~1] = (name, int(value, 16))
    gdb.Breakpoint("*0x%x" % (int(addr, 16) & ~1), internal=True)

while True:
    try:
        gdb.execute("continue", to_string=True)
        pc = reg("pc") & ~1
    except gdb.error:
        break  # the emulator went away
    if pc in forces:
        name, value = forces[pc]
        gdb.execute("set $%s = %d" % (name, value))
    # a function that asked for ":ret" has come back to its caller (same stack pointer as on entry)
    for item in list(pending):
        label, hit, regs, back, sp, bp = item
        if pc == back and reg("sp") == sp:
            regs["ret"] = reg("r0")
            lines.append("%s %d returned 0x%08x" % (label, hit, regs["ret"]))
            save_all(label, hit, regs, lines)
            bp.delete()
            pending.remove(item)
    if pc in entries:
        label, on_return, entry_bp = entries[pc]
        hits[label] += 1
        regs = {"r%d" % i: reg("r%d" % i) for i in range(4)}
        lines.append("%s %d entered r0=0x%08x r1=0x%08x r2=0x%08x r3=0x%08x lr=0x%08x"
                     % (label, hits[label], regs["r0"], regs["r1"], regs["r2"], regs["r3"], reg("lr")))
        if on_return:
            back = reg("lr") & ~1
            pending.append((label, hits[label], regs, back, reg("sp"), gdb.Breakpoint("*0x%x" % back, internal=True)))
        else:
            save_all(label, hits[label], regs, lines)
        if hits[label] >= MAX_HITS:
            entry_bp.enabled = False

with open(os.path.join(OUT, "stops.txt"), "w") as f:
    f.write("\n".join(lines) + "\n")
print("\n".join(lines))
