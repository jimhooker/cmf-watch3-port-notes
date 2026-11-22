#!/usr/bin/env python3
"""Whole-function disassembly of a Watch Pro 2 function and its Watch 3 Pro candidate, with call targets named.

usage: fn_pair.py WP2_APP WP3_APP DATA_DIR OUT_DIR [NAME ...]

With no NAME, dumps every function in address-map.csv whose body is 'similar' or 'rewritten'.
Calls and literal-pool words are annotated with the address-map name or the twin from functions.csv, so the two
sides can be compared call for call. Static analysis only.
"""
import bisect
import csv
import struct
import sys
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, CS_MODE_V8, Cs

BASE = 0x10000000
cs = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS | CS_MODE_V8)


def load(data):
    amap = list(csv.DictReader(open(data / "address-map.csv", newline="")))
    funcs = list(csv.DictReader(open(data / "functions.csv", newline="")))
    return amap, funcs


def main():
    a_img = Path(sys.argv[1]).read_bytes()
    b_img = Path(sys.argv[2]).read_bytes()
    data, out = Path(sys.argv[3]), Path(sys.argv[4])
    out.mkdir(parents=True, exist_ok=True)
    amap, funcs = load(data)

    a_size, a_name, b_name, twin = {}, {}, {}, {}
    for f in funcs:
        a = int(f["wp2_entry"], 16) & ~1
        a_size[a] = int(f["size"])
        src = Path(f["source_file"]).name if f["source_file"] else ""
        a_name[a] = src
        if f["wp3_entry"]:
            b = int(f["wp3_entry"], 16) & ~1
            twin[a] = b
            b_name[b] = "twin_of_%08x%s" % (a, "(" + src + ")" if src else "")
    for r in amap:
        if r["wp2_addr"].startswith("0x"):
            a_name[int(r["wp2_addr"], 16) & ~1] = r["name"]
        if r["wp3_addr"].startswith("0x"):
            b_name[int(r["wp3_addr"], 16) & ~1] = r["name"]
    a_starts = sorted(a_size)
    b_starts = sorted(b_name)

    def label(addr, names, a_side):
        key = addr & ~1
        if key in names and names[key]:
            extra = ""
            if a_side and key in twin:
                extra = " ->wp3 %08x" % twin[key]
            return " <%s%s>" % (names[key], extra)
        if a_side and key in twin:
            return " <->wp3 %08x>" % twin[key]
        return ""

    def dis(img, start, length, names, a_side):
        lines, off = [], start - BASE
        end = start + length
        pools = set()
        addr = start
        while addr < end:
            if addr in pools:
                word = struct.unpack_from("<I", img, addr - BASE)[0]
                lines.append("%08x .word   0x%08x%s" % (addr, word, label(word, names, a_side)))
                addr += 4
                continue
            ins = next(cs.disasm(img[addr - BASE:addr - BASE + 4], addr), None)
            if ins is None:
                lines.append("%08x .short  0x%04x" % (addr, struct.unpack_from("<H", img, addr - BASE)[0]))
                addr += 2
                continue
            note = ""
            ops = ins.op_str
            if ins.mnemonic in ("bl", "b", "b.w", "blx") and ops.startswith("#"):
                note = label(int(ops[1:], 16), names, a_side)
            if "[pc" in ops and ins.mnemonic.startswith(("ldr", "vldr")):
                try:
                    disp = int(ops.split("#")[1].rstrip("]"), 16) if "#" in ops else 0
                    lit = ((addr + 4) & ~3) + disp
                    word = struct.unpack_from("<I", img, lit - BASE)[0]
                    note = "  ; =0x%08x%s" % (word, label(word, names, a_side))
                    if ins.mnemonic.startswith("ldr") and start <= lit < end + 64:
                        pools.add(lit)
                        if lit >= end:
                            end = lit + 4
                except (ValueError, IndexError, struct.error):
                    pass
            lines.append("%08x %-7s %s%s" % (addr, ins.mnemonic, ops, note))
            addr += ins.size
        return lines

    wanted = sys.argv[5:]
    rows = [r for r in amap if (r["name"] in wanted if wanted else r["body"] in ("similar", "rewritten"))]
    done = 0
    for r in rows:
        if r["kind"] != "function" or not r["wp3_addr"].startswith("0x"):
            continue
        a = int(r["wp2_addr"], 16) & ~1
        b = int(r["wp3_addr"], 16) & ~1
        if not (BASE <= a < BASE + len(a_img) and BASE <= b < BASE + len(b_img)):
            continue
        done += 1
        asz = a_size.get(a)
        if asz is None:
            i = bisect.bisect_right(a_starts, a)
            asz = (a_starts[i] - a) if i < len(a_starts) else 64
        i = bisect.bisect_right(b_starts, b)
        nxt = b_starts[i] if i < len(b_starts) else b + asz
        bsz = min(nxt - b, max(asz * 2, 96))
        text = ["# %s  body=%s  how=%s votes=%s similarity=%s" % (r["name"], r["body"], r["how"], r["votes"], r["similarity"]),
                "# sdk: %s:%s" % (r["sdk_file"], r["sdk_line"]),
                "", "## Watch Pro 2 @ %08x (%d bytes)" % (a, asz)]
        text += dis(a_img, a, asz, a_name, True)
        text += ["", "## Watch 3 Pro candidate @ %08x (showing %d bytes; next known function at %08x)" % (b, bsz, nxt)]
        text += dis(b_img, b, bsz, b_name, False)
        (out / (r["name"] + ".txt")).write_text("\n".join(text) + "\n")
    print("wrote %d files to %s" % (done, out))


if __name__ == "__main__":
    main()
