#!/usr/bin/env python3
"""BinDiff-lite between two Actions/Zephyr Thumb-2 app images.

Finds, for addresses known in image A (Watch Pro 2), the corresponding address in image B (Watch 3 Pro):
  1. masked instruction signatures (call targets, literal displacements and address immediates wildcarded)
  2. propagation through aligned call sites / literal pools of matched functions

usage: match.py WP2_APP_BIN WP3_APP_BIN WP2_FUNCTION_MAP_TSV SDK_ADDRS_JSON OUT_JSON

WP2_FUNCTION_MAP_TSV is dumps/analysis/function_map.tsv from cmf-watch-utils (entry, size per function).
Needs: pip install capstone numpy. Static analysis only: a "located" address is a candidate, not a tested one.
"""
import bisect
import difflib
import collections
import json
import re
import struct
import sys
import time

import numpy as np
from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, CS_MODE_V8, Cs

BASE = 0x10000000
COND = {"eq", "ne", "hs", "cs", "lo", "cc", "mi", "pl", "vs", "vc", "hi", "ls", "ge", "lt", "gt", "le"}
K_NONE, K_CALL, K_JUMP, K_COND, K_LIT, K_ADR, K_MOVW, K_MOVT = range(8)
M64 = (1 << 64) - 1
PRIMES = (0x9E3779B97F4A7C15, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9, 0x27D4EB2F165667C5)

TOK = {}
IMM = re.compile(r"#(-?0x[0-9a-f]+|-?\d+)")


def tid(s):
    i = TOK.get(s)
    if i is None:
        i = len(TOK) + 1
        TOK[s] = i
    return i


def parse_imm(ops):
    m = IMM.findall(ops)
    return int(m[-1], 0) if m else None


def normalize(ad, sz, m, ops):
    base = m[:-2] if m.endswith(".w") else m
    kind = K_NONE
    val = None
    term = False
    if base == "b" and ops.startswith("#"):
        kind, val, tok, term = K_JUMP, parse_imm(ops), "b", True
    elif base in ("bl", "blx") and ops.startswith("#"):
        kind, val, tok = K_CALL, parse_imm(ops), "bl"
    elif base[:1] == "b" and base[1:] in COND and ops.startswith("#"):
        val = parse_imm(ops)
        kind, tok = K_COND, f"{base} {val - ad}"
    elif base[:2] == "bl" and base[2:] in COND and ops.startswith("#"):
        kind, val, tok = K_CALL, parse_imm(ops), base
    elif base in ("cbz", "cbnz"):
        val = parse_imm(ops)
        kind, tok = K_COND, f"{base} {ops.split(',')[0]} {val - ad}"
    elif base in ("tbb", "tbh"):
        tok, term = m + " " + ops, True
    elif "[pc" in ops:
        disp = parse_imm(ops) or 0
        val = ((ad + 4) & ~3) + disp
        kind, tok = K_LIT, f"{m} {ops.split('[pc')[0]}[pc]"
    elif base == "adr":
        val = ((ad + 4) & ~3) + (parse_imm(ops) or 0)
        kind, tok = K_ADR, f"{m} {ops.split(',')[0]}"
    elif base in ("movw", "movt"):
        kind = K_MOVW if base == "movw" else K_MOVT
        val, tok = parse_imm(ops), f"{m} {ops.split(',')[0]}"
    else:
        tok = m + " " + ops
        if base in ("bx", "udf") or (base == "pop" and "pc" in ops) or (base in ("mov", "ldr") and ops.startswith("pc,")):
            term = True
    if kind == K_JUMP:
        loose = "b"
    elif kind == K_CALL:
        loose = "bl"
    elif kind == K_COND:
        loose = base if base not in ("cbz", "cbnz") else f"{base} {ops.split(',')[0]}"
    elif kind == K_LIT:
        loose = f"{base} {ops.split('[pc')[0]}[pc]"
    elif kind == K_ADR:
        loose = f"adr {ops.split(',')[0]}"
    elif kind in (K_MOVW, K_MOVT):
        loose = f"{'mov' if kind == K_MOVW else 'movt'} {ops.split(',')[0]}, #"
    else:
        loose = base + " " + IMM.sub("#", ops)
    return (sz, tid(f"{sz}:{tok}"), kind, val, term, tid("L:" + loose))


class Image:
    def __init__(self, path):
        self.data = open(path, "rb").read()
        self.size = len(self.data)
        self.end = BASE + self.size
        self.cs = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS | CS_MODE_V8)
        self.cache = {}

    def has(self, addr):
        return BASE <= addr < self.end

    def u32(self, addr):
        o = addr - BASE
        if 0 <= o <= self.size - 4:
            return struct.unpack_from("<I", self.data, o)[0]
        return None

    def insn(self, addr):
        r = self.cache.get(addr, 0)
        if r != 0:
            return r
        o = addr - BASE
        r = None
        if 0 <= o <= self.size - 2 and not (addr & 1):
            for (ad, sz, m, ops) in self.cs.disasm_lite(self.data[o:o + 4], addr, 1):
                r = normalize(ad, sz, m, ops)
        self.cache[addr] = r
        return r

    def cstr(self, addr, minlen=4, maxlen=96):
        o = addr - BASE
        if not (0 <= o < self.size):
            return None
        end = self.data.find(b"\0", o, o + maxlen)
        if end < 0:
            return None
        s = self.data[o:end]
        if len(s) >= minlen and all(32 <= c < 127 or c in (9, 10) for c in s):
            return s
        return None


def build_index(img):
    n = img.size // 2
    tok = np.zeros(n + 1, dtype=np.uint64)
    szh = np.zeros(n + 1, dtype=np.int64)
    for o in range(0x200, img.size - 1, 2):
        r = img.insn(BASE + o)
        if r is not None:
            tok[o >> 1] = r[1]
            szh[o >> 1] = r[0] >> 1
    idx = np.arange(n + 1)
    nxt = np.minimum(np.where(szh > 0, idx + szh, n), n)
    n1 = nxt
    n2 = nxt[n1]
    n3 = nxt[n2]
    valid = (tok > 0) & (tok[n1] > 0) & (tok[n2] > 0) & (tok[n3] > 0)
    p = [np.uint64(x) for x in PRIMES]
    with np.errstate(over="ignore"):
        h = tok * p[0] + tok[n1] * p[1] + tok[n2] * p[2] + tok[n3] * p[3]
    cand = np.nonzero(valid)[0]
    hv = h[cand]
    order = np.argsort(hv, kind="stable")
    return hv[order], cand[order]


def hash4(t):
    return (t[0] * PRIMES[0] + t[1] * PRIMES[1] + t[2] * PRIMES[2] + t[3] * PRIMES[3]) & M64


def lookup(index, t4):
    hs, cands = index
    h = np.uint64(hash4(t4))
    lo = int(np.searchsorted(hs, h, "left"))
    hi = int(np.searchsorted(hs, h, "right"))
    return [BASE + 2 * int(i) for i in cands[lo:hi]]


def prefix(img, addr, cap=32, stop_at_term=True):
    out = []
    a = addr
    while len(out) < cap:
        r = img.insn(a)
        if r is None:
            break
        out.append((a, r))
        if r[4] and stop_at_term:
            break
        a += r[0]
    return out


def pwalk(A, B, a, b, bound):
    """Walk A from a and B from b in lock-step. Returns (pairs, status)."""
    pend = set()
    pa, pb = a, b
    pairs = []
    status = "end"
    guard = 0
    while pa < bound and guard < 20000:
        guard += 1
        ra = A.insn(pa)
        rb = B.insn(pb)
        if ra is None or rb is None or ra[1] != rb[1]:
            status = "mismatch"
            break
        kind = ra[2]
        if kind == K_JUMP:
            ta, tb = ra[3], rb[3]
            inside = a <= ta < bound
            if inside and (ta - pa) != (tb - pb):
                status = "mismatch"
                break
            if inside and ta > pa:
                pend.add(ta - a)
        elif kind == K_COND:
            ta = ra[3]
            if a <= ta < bound and ta > pa:
                pend.add(ta - a)
        pairs.append((pa, pb, ra, rb))
        if ra[4]:
            cur = pa - a
            nxt = min((t for t in pend if t > cur), default=None)
            if nxt is None:
                break
            pa, pb = a + nxt, b + nxt
        else:
            pa += ra[0]
            pb += rb[0]
    else:
        if pa >= bound:
            status = "bound"
    return pairs, status


def lin(img, start, span, cap=1500):
    out = []
    a = start
    end = start + span
    while a < end and len(out) < cap:
        r = img.insn(a)
        if r is None:
            a += 2
            continue
        out.append((a, r))
        a += r[0]
    return out


def fuzzy(A, B, a, b, span):
    la = lin(A, a, span)
    lb = lin(B, b, int(span * 1.6) + 64)
    sm = difflib.SequenceMatcher(None, [r[5] for _, r in la], [r[5] for _, r in lb], autojunk=False)
    blocks = [blk for blk in sm.get_matching_blocks() if blk.size >= 3]
    matched = sum(blk.size for blk in blocks)
    return la, lb, blocks, matched / max(1, len(la))


def main():
    a_path, b_path, fmap_path, addrs_path, out_path = sys.argv[1:6]
    t0 = time.time()
    A = Image(a_path)
    B = Image(b_path)
    fa = []
    fsize = {}
    for line in open(fmap_path).read().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].startswith("0x"):
            e = int(parts[0], 16)
            fa.append(e)
            fsize[e] = int(parts[1])
    fa_set = set(fa)
    code_end = max(e + fsize[e] for e in fa)
    needed_raw = [o for o in json.load(open(addrs_path)) if o["where"] == "code"]
    needed = {}
    for o in needed_raw:
        needed.setdefault(o["addr"], o)
    need_rom = sorted(x for x in needed if A.has(x))
    need_ram = sorted(x for x in needed if 0x2F000000 <= x < 0x40000000 and (x >> 20) != 0x381)

    def is_fn_ptr(x):
        t = x & ~1
        if t in fa_set:
            return True
        if not (x & 1):
            return False
        # odd address: Thumb function pointer unless it is plainly a string / past the code
        if A.cstr(x) is not None and t >= code_end:
            return False
        return t < code_end

    extra_entries = {x & ~1 for x in need_rom if is_fn_ptr(x)} - fa_set
    entries = sorted(fa_set | extra_entries)
    entry_set = set(entries)
    print(f"A {A.size} B {B.size} | A functions {len(fa)} (+{len(extra_entries)} SDK-only entries) code_end {code_end:#x}")

    index = build_index(B)
    print(f"B index: {len(index[0])} windows, {time.time() - t0:.1f}s")

    def next_entry(a):
        i = bisect.bisect_right(entries, a)
        return entries[i] if i < len(entries) else A.end

    def bound_of(a):
        return min(next_entry(a), a + 0x6000)

    def span_of(a):
        sz = fsize.get(a, 0)
        nb = bound_of(a) - a
        return min(nb, sz) if sz else nb

    # ---- pass 1: strict signatures -----------------------------------------
    sig = {}
    for a in entries:
        P = prefix(A, a)
        if len(P) < 4:
            sig[a] = {"cls": "short", "n": len(P)}
            continue
        cands = lookup(index, [r[1] for _, r in P[:4]])
        full = []
        for b in cands:
            pb = b
            ok = True
            for (_, ra) in P:
                rb = B.insn(pb)
                if rb is None or rb[1] != ra[1]:
                    ok = False
                    break
                pb += rb[0]
            if ok:
                full.append(b)
        if not full:
            sig[a] = {"cls": "none", "n": len(P)}
            continue
        bound = bound_of(a)
        scored = []
        for b in full[:200]:
            pairs, status = pwalk(A, B, a, b, bound)
            scored.append((len(pairs), status in ("end", "bound"), b))
        complete = [s for s in scored if s[1]]
        if len(complete) == 1:
            sig[a] = {"cls": "unique", "b": complete[0][2], "n": complete[0][0]}
        elif len(complete) > 1:
            sig[a] = {"cls": "ambiguous", "cands": [s[2] for s in complete][:50], "n": complete[0][0]}
        else:
            scored.sort(reverse=True)
            if len(scored) == 1 or scored[0][0] >= 2 * max(scored[1][0], 4):
                sig[a] = {"cls": "partial", "b": scored[0][2], "n": scored[0][0]}
            else:
                sig[a] = {"cls": "ambiguous-partial", "cands": [s[2] for s in scored][:50], "n": scored[0][0]}
    # the mapping must be one-to-one: several A functions "uniquely" hitting one B function are twins on the A side
    claim = collections.Counter(v["b"] for v in sig.values() if v["cls"] == "unique")
    twins = 0
    for a, v in sig.items():
        if v["cls"] == "unique" and claim[v["b"]] > 1:
            sig[a] = {"cls": "ambiguous", "cands": [v["b"]], "n": v["n"]}
            twins += 1
    c1 = collections.Counter(v["cls"] for v in sig.values())
    print("pass1 signature classes:", dict(c1), f"(A-side twins demoted {twins})", f"{time.time() - t0:.1f}s")

    # ---- pass 2: propagation (strict walks, then fuzzy walks) ----------------
    anchors = {}
    fvotes = collections.defaultdict(collections.Counter)
    dvotes = collections.defaultdict(collections.Counter)
    rvotes = collections.defaultdict(collections.Counter)
    lslot, imap = {}, {}
    fvotes_l = collections.defaultdict(collections.Counter)
    dvotes_l = collections.defaultdict(collections.Counter)
    rvotes_l = collections.defaultdict(collections.Counter)
    lslot_l, imap_l = {}, {}
    constdiff = []
    walked, fuzzed = set(), set()
    complete_walk = {}
    ratio = {}

    def vote(a_lo, a_hi, ra, rb, FV, DV, RV, LS):
        k = ra[2]
        if k != rb[2]:
            return
        if k == K_CALL or (k == K_JUMP and not (a_lo <= ra[3] < a_hi)):
            if ra[3] is not None and rb[3] is not None and A.has(ra[3]) and B.has(rb[3]):
                FV[ra[3] & ~1][rb[3] & ~1] += 1
        elif k == K_LIT:
            la, lb = ra[3], rb[3]
            LS.setdefault(la, lb)
            va, vb = A.u32(la), B.u32(lb)
            if va is None or vb is None:
                return
            if A.has(va) and B.has(vb):
                if (va & 1) and (vb & 1) and (va & ~1) in entry_set:
                    FV[va & ~1][vb & ~1] += 1
                else:
                    DV[va][vb] += 1
            elif 0x20000000 <= va < 0x40000000 and 0x20000000 <= vb < 0x40000000:
                RV[va][vb] += 1
            elif va != vb and not A.has(va) and not B.has(vb) and LS is lslot:
                constdiff.append((la, lb, va, vb))
        elif k == K_ADR:
            if A.has(ra[3]) and B.has(rb[3]):
                DV[ra[3]][rb[3]] += 1

    def walk_anchor(a, b):
        if a in walked:
            return
        walked.add(a)
        bound = bound_of(a)
        pairs, status = pwalk(A, B, a, b, bound)
        complete_walk[a] = status in ("end", "bound")
        for (pa, pb, ra, rb) in pairs:
            imap.setdefault(pa, pb)
            vote(a, bound, ra, rb, fvotes, dvotes, rvotes, lslot)

    def fuzz_anchor(a, b):
        if a in fuzzed:
            return
        fuzzed.add(a)
        span = span_of(a)
        la, lb, blocks, r = fuzzy(A, B, a, b, span)
        ratio[a] = r
        if r < 0.35:
            return
        for blk in blocks:
            for i in range(blk.size):
                pa, ra = la[blk.a + i]
                pb, rb = lb[blk.b + i]
                imap_l.setdefault(pa, pb)
                vote(a, a + span, ra, rb, fvotes_l, dvotes_l, rvotes_l, lslot_l)

    for a, v in sig.items():
        if v["cls"] == "unique":
            anchors[a] = (v["b"], "signature")
    rounds = 0
    while True:
        rounds += 1
        for a, (b, _) in list(anchors.items()):
            walk_anchor(a, b)
        for a, (b, _) in list(anchors.items()):
            if not complete_walk.get(a, False):
                fuzz_anchor(a, b)
        new = 0
        claimed = collections.Counter(b for b, _ in anchors.values())
        cand_as = set(fvotes) | set(fvotes_l)
        for ta in cand_as:
            if ta in anchors:
                continue
            strict = fvotes.get(ta)
            cnt = collections.Counter()
            if strict:
                for k, n in strict.items():
                    cnt[k] += 2 * n
            loose = fvotes_l.get(ta)
            if loose:
                for k, n in loose.items():
                    cnt[k] += n
            top = cnt.most_common(2)
            tb, n = top[0]
            if len(top) > 1 and top[1][1] * 2 > n:
                continue
            if claimed[tb]:
                continue
            if not strict and n < 2:
                continue   # a single loose vote is not enough
            s = sig.get(ta)
            if s and s["cls"] == "partial" and s["b"] != tb and n < 4:
                continue
            anchors[ta] = (tb, "callgraph" if strict and strict.get(tb) else "callgraph-loose")
            claimed[tb] += 1
            new += 1
        if new == 0:
            for a, v in sig.items():
                if v["cls"] == "partial" and a not in anchors and not claimed[v["b"]] and v["n"] >= 12:
                    anchors[a] = (v["b"], "signature-partial")
                    claimed[v["b"]] += 1
                    new += 1
        if new == 0 or rounds > 60:
            break
    src = collections.Counter(s for _, s in anchors.values())
    print(f"pass2: anchors {len(anchors)} {dict(src)} rounds {rounds} | strict imap {len(imap)} loose imap {len(imap_l)} "
          f"{time.time() - t0:.1f}s")

    # ---- self-checks --------------------------------------------------------
    agree = disagree = 0
    disagreements = []
    for a, v in sig.items():
        if v["cls"] == "unique" and a in fvotes:
            tb, n = fvotes[a].most_common(1)[0]
            if tb == v["b"]:
                agree += 1
            else:
                disagree += 1
                disagreements.append((a, v["b"], tb, n))
    inj = collections.Counter(b for b, _ in anchors.values())
    dup = sum(1 for b, n in inj.items() if n > 1)
    print(f"check: signature-vs-callgraph agree {agree} disagree {disagree} | B entries claimed twice {dup}")

    def body_class(a, b):
        if complete_walk.get(a) is None:
            walk_anchor(a, b)
        if complete_walk.get(a):
            return "identical", 1.0
        if a not in ratio:
            fuzz_anchor(a, b)
        r = ratio.get(a, 0.0)
        return ("same-shape" if r >= 0.9 else "similar" if r >= 0.6 else "rewritten"), r

    def best(*counters):
        cnt = collections.Counter()
        w = 2
        for c in counters:
            if c:
                for k, n in c.items():
                    cnt[k] += w * n
            w = 1
        top = cnt.most_common(2)
        if not top:
            return None, 0, 0
        return top[0][0], top[0][1], (top[1][1] if len(top) > 1 else 0)

    fa_sorted = sorted(fa)

    def in_code(t):
        i = bisect.bisect_right(fa_sorted, t) - 1
        if i < 0:
            return False
        e = fa_sorted[i]
        return t < e + fsize.get(e, 0)

    results = []
    for x in need_rom:
        o = needed[x]
        rec = {"addr": x, "name": o["name"], "file": o["file"], "line": o["line"]}
        t = x & ~1
        if is_fn_ptr(x):
            rec["kind"] = "function"
            s = sig.get(t, {"cls": "n/a"})
            rec["sig"] = s["cls"]
            if t in anchors:
                b, source = anchors[t]
                rec["b"] = b | (x & 1)
                rec["source"] = source
                rec["body"], rec["ratio"] = body_class(t, b)
                vb, n, n2 = best(fvotes.get(t), fvotes_l.get(t))
                rec["votes"] = n
                if source == "signature" and vb is not None and vb != b:
                    rec["status"] = "conflict"
                else:
                    rec["status"] = "located"
            else:
                rec["status"] = "unresolved"
                if "cands" in s:
                    rec["cands"] = len(s["cands"])
        else:
            strict_hit = True
            if t in imap:
                rec.update(kind="code-site", b=imap[t], status="located", source="aligned")
            elif t in lslot:
                rec.update(kind="literal-slot", b=lslot[t], status="located", source="aligned")
            elif t in imap_l and in_code(t):
                rec.update(kind="code-site", b=imap_l[t], status="located", source="aligned-loose")
            elif t in lslot_l:
                rec.update(kind="literal-slot", b=lslot_l[t], status="located", source="aligned-loose")
            elif t in dvotes or t in dvotes_l:
                vb, n, n2 = best(dvotes.get(t), dvotes_l.get(t))
                rec.update(kind="data", b=vb, status="located" if n2 * 2 <= n else "conflict", votes=n,
                           source="data-ref" if t in dvotes else "data-ref-loose")
            else:
                sraw = A.cstr(x) or A.cstr(t)
                hit = None
                if sraw is not None:
                    needle = sraw + b"\0"
                    first = B.data.find(needle)
                    if first >= 0 and B.data.find(needle, first + 1) < 0:
                        hit = BASE + first
                if hit is not None:
                    rec.update(kind="string", b=hit, status="located", source="string")
                else:
                    P = prefix(A, t, cap=8, stop_at_term=False)
                    ic = in_code(t)
                    cands = lookup(index, [r[1] for _, r in P[:4]]) if (ic and len(P) >= 6) else []
                    full = []
                    for b in cands:
                        pb = b
                        ok = True
                        for (_, ra) in P:
                            rb = B.insn(pb)
                            if rb is None or rb[1] != ra[1]:
                                ok = False
                                break
                            pb += rb[0]
                        if ok:
                            full.append(b)
                    if len(full) == 1:
                        rec.update(kind="code-site", b=full[0], status="located", source="window")
                    else:
                        near = None
                        for d in range(4, 0x200, 4):
                            if (t - d) in dvotes or (t - d) in dvotes_l:
                                vb, n, n2 = best(dvotes.get(t - d), dvotes_l.get(t - d))
                                near = (d, vb)
                                break
                        if near and not ic:
                            rec.update(kind="data", b=near[1] + near[0], status="derived", delta=near[0], source="base+offset")
                        else:
                            kind = "code-site" if ic else ("patch-area" if t >= A.end - 0x400 else "data")
                            rec.update(kind=kind, status="unresolved")
            if "b" in rec and rec["kind"] == "literal-slot":
                rec["a_val"], rec["b_val"] = A.u32(t), B.u32(rec["b"])
        results.append(rec)

    ram_results = []
    for x in need_ram:
        o = needed[x]
        rec = {"addr": x, "name": o["name"], "file": o["file"], "line": o["line"], "kind": "ram"}
        if x in rvotes or x in rvotes_l:
            vb, n, n2 = best(rvotes.get(x), rvotes_l.get(x))
            rec.update(b=vb, status="located" if n2 * 2 <= n else "conflict", votes=n,
                       source="data-ref" if x in rvotes else "data-ref-loose")
        else:
            near = None
            for d in range(1, 0x400):
                if (x - d) in rvotes or (x - d) in rvotes_l:
                    vb, n, n2 = best(rvotes.get(x - d), rvotes_l.get(x - d))
                    near = (d, vb)
                    break
            if near:
                rec.update(b=near[1] + near[0], status="derived", delta=near[0], source="base+offset")
            else:
                rec.update(status="unresolved")
        ram_results.append(rec)

    # whole-image picture: how much of A's code has an identical / similar twin in B
    bodies = collections.Counter()
    fmap = []
    for a in fa:
        c = body_class(a, anchors[a][0])[0] if a in anchors else "no counterpart found"
        bodies[c] += 1
        fmap.append([a, fsize[a], c])

    summary = {
        "a_functions": len(fa),
        "sig_classes": dict(c1),
        "anchors": len(anchors),
        "anchor_sources": dict(src),
        "all_functions_body": dict(bodies),
        "check": {"agree": agree, "disagree": disagree, "b_claimed_twice": dup},
        "rom_total": len(results),
        "rom_status": dict(collections.Counter(r["status"] for r in results)),
        "rom_by_kind": {k: dict(collections.Counter(r["status"] for r in results if r["kind"] == k))
                        for k in sorted({r["kind"] for r in results})},
        "function_bodies": dict(collections.Counter(r.get("body", "-") for r in results if r["kind"] == "function")),
        "ram_status": dict(collections.Counter(r["status"] for r in ram_results)),
        "constdiff": len(constdiff),
    }
    json.dump({"summary": summary, "rom": results, "ram": ram_results, "fmap": fmap, "code_end": code_end,
               "anchors": {hex(a): [hex(b), s] for a, (b, s) in sorted(anchors.items())},
               "disagreements": [[hex(v) for v in d[:3]] + [d[3]] for d in disagreements],
               "constdiff": [[hex(x) for x in c] for c in constdiff[:400]]},
              open(out_path, "w"), indent=1)
    print(json.dumps(summary, indent=1))
    print(f"done {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
