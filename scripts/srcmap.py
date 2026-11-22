#!/usr/bin/env python3
"""Attribute Watch Pro 2 functions to source files using the __FILE__ path strings baked into the firmware.

A function that loads the address of a "…/something.c" string (assert/log macros do) belongs to that file;
functions sitting between two functions of the same file are assumed to belong to it too.
Coverage is partial (about 13% of code bytes on 1.0.0.73) but the paths reveal the source tree and where
each library sits in the image.

usage: srcmap.py WP2_APP_BIN MATCH_JSON OUT_JSON
"""
import bisect
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import match as M  # noqa: E402


def main():
    a_path, mj, outp = sys.argv[1:4]
    A = M.Image(a_path)
    R = json.load(open(mj))
    fmap = R["fmap"]
    cls = {e: c for e, s, c in fmap}
    size = {e: s for e, s, c in fmap}
    entries = sorted(cls)
    runs = []
    for m in re.finditer(rb"[\x20-\x7e]{3,160}\.[ch]\x00", A.data):
        runs.append((M.BASE + m.start(), M.BASE + m.end() - 1, m.group(0)[:-1].decode()))
    starts = [r[0] for r in runs]

    def file_at(v):
        i = bisect.bisect_right(starts, v) - 1
        if i < 0:
            return None
        s, e, txt = runs[i]
        if s <= v < e:
            t = txt[v - s:]
            if re.fullmatch(r"[A-Za-z0-9_./\-]+\.[ch]", t):
                return t
        return None

    attr = {}
    for e in entries:
        cnt = collections.Counter()
        a, end, n = e, e + size[e], 0
        while a < end and n < 4000:
            r = A.insn(a)
            n += 1
            if r is None:
                a += 2
                continue
            if r[2] == M.K_LIT:
                v = A.u32(r[3])
                if v is not None:
                    f = file_at(v)
                    if f:
                        cnt[f] += 1
            a += r[0]
        if cnt:
            attr[e] = cnt.most_common(1)[0][0]
    known = sorted(attr)
    filled = dict(attr)
    for x, y in zip(known, known[1:]):
        if attr[x] == attr[y]:
            i, j = bisect.bisect_right(entries, x), bisect.bisect_left(entries, y)
            for e in entries[i:j]:
                filled[e] = attr[x]
    tot = sum(size.values())
    print(f"path strings {len(runs)} | functions {len(entries)} | attributed directly {len(attr)} | "
          f"after fill {len(filled)} ({100 * sum(size[e] for e in filled) / tot:.0f}% of code bytes)")
    K = {"identical": 0, "same-shape": 1, "similar": 1, "rewritten": 1, "no counterpart found": 2}
    agg = collections.defaultdict(lambda: [0, 0, 0, 0, None])
    for e, p in filled.items():
        a = agg[p]
        a[K[cls[e]]] += size[e]
        a[3] += 1
        a[4] = e if a[4] is None else min(a[4], e)
    json.dump({"attr": {hex(e): p for e, p in filled.items()},
               "files": {k: {"same": v[0], "changed": v[1], "none": v[2], "functions": v[3], "first": hex(v[4])}
                         for k, v in agg.items()}}, open(outp, "w"), indent=1)
    for k, (a, b, c, n, lo) in sorted(agg.items(), key=lambda kv: kv[1][4]):
        t = a + b + c
        print(f"{lo:#x} {k[-60:]:60s} {n:4d} fns {t / 1024:6.1f}K  same {100 * a / t:3.0f}% changed {100 * b / t:3.0f}% none {100 * c / t:3.0f}%")


if __name__ == "__main__":
    main()
