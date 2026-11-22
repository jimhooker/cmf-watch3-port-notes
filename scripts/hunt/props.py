"""Align the ux2sys property table of the Watch Pro 2 with the Watch 3 Pro one.

usage (from the project root): scripts/hunt/props.py [OUT.csv]
Each row is {setter, getter, length}. Rows are aligned with a gap-allowing sequence alignment scored on: matched
twin handlers, shared log strings, equal length, same setter/getter presence, and instruction-shape similarity.
Static analysis only.
"""
import sys, difflib, csv, re
sys.path.insert(0, 'scripts/hunt')
from lib import *

T2, N2 = 0x101f4274, 0x9f
T3, N3 = 0x10220de4, 0xd4

def row(img, t, i): return tuple(w(img, t + 12 * i + 4 * k) for k in range(3))

_shape = {}
def shape(img, fn, n=40):
    key = (id(img), fn)
    if key not in _shape:
        out = []; strs = set(); rams = []
        a = fn & ~1
        for _ in range(n):
            i = next(cs.disasm(img[a - BASE:a - BASE + 4], a), None)
            if i is None: break
            ops = i.op_str
            if i.mnemonic.startswith('ldr') and '[pc' in ops:
                d = int(ops.split('#')[1].rstrip(']'), 16) if '#' in ops else 0
                l = ((a + 4) & ~3) + d
                if l - BASE + 4 <= len(img):
                    v = w(img, l); s = cstr(img, v, 8)
                    if s: strs.add(s)
                    elif 0x2ff00000 <= v < 0x38800000: rams.append(v)
                ops = re.sub(r'#0x[0-9a-f]+', '#L', ops)
            elif i.mnemonic in ('bl', 'b', 'b.w', 'blx') or i.mnemonic.startswith('b') and ops.startswith('#') or i.mnemonic in ('cbz', 'cbnz'):
                ops = re.sub(r'#0x[0-9a-f]+', '#T', ops)
            out.append(i.mnemonic + ' ' + ops)
            if (i.mnemonic in ('pop', 'pop.w') and 'pc' in ops) or i.mnemonic == 'bx': break
            a += i.size
        _shape[key] = (out, strs, rams)
    return _shape[key]

def fsim(f2, f3):
    """similarity of two handlers: 0..1, and whether it is a hard identification"""
    if not f2 and not f3: return 1.0, False
    if bool(f2) != bool(f3): return -1.0, False
    if twin.get(f2 & ~1) == (f3 & ~1): return 1.0, True
    s2, st2, _ = shape(A, f2); s3, st3, _ = shape(B, f3)
    common = {s for s in st2 & st3 if not s.endswith('.c')}
    if common: return 1.0, True
    return difflib.SequenceMatcher(None, s2, s3).ratio(), False

def score(i, j):
    a = row(A, T2, i); b = row(B, T3, j)
    ss, hs = fsim(a[0], b[0]); sg, hg = fsim(a[1], b[1])
    sc = 0.0
    sc += 3 if a[2] == b[2] else -3
    for s, h, present in ((ss, hs, a[0] or b[0]), (sg, hg, a[1] or b[1])):
        if s < 0: sc -= 4
        elif h: sc += 8
        elif present: sc += 6 * (s - 0.45)
        else: sc += 0.5
    return sc, (hs or hg)

def align():
    GAP = -1.0
    S = [[0.0] * (N3 + 1) for _ in range(N2 + 1)]; P = [[0] * (N3 + 1) for _ in range(N2 + 1)]
    for i in range(1, N2 + 1): S[i][0] = S[i - 1][0] + GAP; P[i][0] = 1
    for j in range(1, N3 + 1): S[0][j] = S[0][j - 1] + GAP; P[0][j] = 2
    sc = {}
    for i in range(1, N2 + 1):
        for j in range(1, N3 + 1):
            sc[(i, j)] = score(i - 1, j - 1)
            best = max((S[i - 1][j - 1] + sc[(i, j)][0], 0), (S[i - 1][j] + GAP, 1), (S[i][j - 1] + GAP, 2))
            S[i][j], P[i][j] = best
    i, j = N2, N3; pairs = []
    while i or j:
        p = P[i][j]
        if p == 0: pairs.append((i - 1, j - 1, sc[(i, j)])); i -= 1; j -= 1
        elif p == 1: pairs.append((i - 1, None, None)); i -= 1
        else: pairs.append((None, j - 1, None)); j -= 1
    return pairs[::-1]

if __name__ == '__main__':
    pairs = align()
    out = []
    for i, j, s in pairs:
        a = row(A, T2, i) if i is not None else None; b = row(B, T3, j) if j is not None else None
        if i is not None and j is not None:
            conf = 'anchored' if s[1] else ('shape' if s[0] >= 4 else 'weak')
        else: conf = 'wp2-only' if j is None else 'wp3-only'
        out.append(['0x%02x' % i if i is not None else '', '0x%02x' % j if j is not None else '',
                    '0x%08x' % a[0] if a else '', '0x%08x' % a[1] if a else '', a[2] if a else '',
                    '0x%08x' % b[0] if b else '', '0x%08x' % b[1] if b else '', b[2] if b else '',
                    conf, '%.1f' % s[0] if s else ''])
    hdr = ['wp2_id', 'wp3_id', 'wp2_set', 'wp2_get', 'wp2_len', 'wp3_set', 'wp3_get', 'wp3_len', 'evidence', 'score']
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'w', newline='') as f:
            wr = csv.writer(f); wr.writerow(hdr); wr.writerows(out)
    import collections
    print(collections.Counter(r[8] for r in out))
    for r in out: print(' '.join('%-10s' % x for x in r))
