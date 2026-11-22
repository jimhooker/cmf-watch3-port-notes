# Runs inside gdb (gdb -batch -x emu_hits_gdb.py), attached to the emulator's CPU debugger.
# Breaks on every candidate Watch 3 Pro function address in address-map.csv, records the first few calls
# (arguments, caller, any string argument) and writes them to a CSV. Emulator only; nothing touches a watch.
#
# Environment: EMU_GDB_PORT, EMU_ADDR_MAP (address-map.csv), EMU_HITS_OUT (output csv), EMU_MAX_HITS (default 3)
import csv
import os

import gdb

PORT = int(os.environ["EMU_GDB_PORT"])
ADDR_MAP = os.environ["EMU_ADDR_MAP"]
OUT = os.environ["EMU_HITS_OUT"]
MAX_HITS = int(os.environ.get("EMU_MAX_HITS", "3"))

rows = []
counts = {}


def reg(name):
    return int(gdb.parse_and_eval("$" + name)) & 0xFFFFFFFF


def cstring(addr):
    """Printable C string at addr, or '' when it is not one."""
    if not (0x10000000 <= addr < 0x11000000 or 0x2FF00000 <= addr < 0x30100000 or 0x38000000 <= addr < 0x38800000):
        return ""
    try:
        raw = bytes(gdb.selected_inferior().read_memory(addr, 48))
    except gdb.MemoryError:
        return ""
    text = raw.split(b"\0", 1)[0]
    if len(text) < 2 or len(text) == 48 or any(b < 0x20 or b > 0x7E for b in text):
        return ""
    return text.decode("ascii")


class Probe(gdb.Breakpoint):
    def __init__(self, name, addr):
        super().__init__("*0x%x" % (addr & ~1), gdb.BP_BREAKPOINT, internal=True)
        self.fn = name
        self.addr = addr
        counts[name] = 0

    def stop(self):
        counts[self.fn] += 1
        args = [reg("r%d" % i) for i in range(4)]
        strings = ["%s=%r" % ("r%d" % i, s) for i, s in ((i, cstring(a)) for i, a in enumerate(args)) if s]
        rows.append([self.fn, "0x%08x" % self.addr, counts[self.fn]] + ["0x%08x" % a for a in args]
                    + ["0x%08x" % reg("lr"), "; ".join(strings)])
        if counts[self.fn] >= MAX_HITS:
            self.enabled = False
        return False


def write():
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "wp3_addr", "hit", "r0", "r1", "r2", "r3", "lr", "strings"])
        w.writerows(rows)
    with open(OUT + ".counts", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "hits_recorded"])
        for name in sorted(counts):
            w.writerow([name, counts[name]])


gdb.execute("set pagination off")
gdb.execute("set confirm off")
gdb.execute("set architecture armv8-m.main")
gdb.execute("target remote 127.0.0.1:%d" % PORT)
with open(ADDR_MAP, newline="") as f:
    for r in csv.DictReader(f):
        if r["kind"] == "function" and r["wp3_addr"].startswith("0x"):
            Probe(r["name"], int(r["wp3_addr"], 16))
gdb.events.exited.connect(lambda e: write())
try:
    gdb.execute("continue")
except gdb.error as e:
    print("stopped:", e)
write()
print("probes: %d, called at least once: %d" % (len(counts), sum(1 for c in counts.values() if c)))
