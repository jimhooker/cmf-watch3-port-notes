"""Independent check of the property-ID alignment: compare the IDs passed at ux2sys call sites inside matched
function pairs. usage (from the project root): scripts/hunt/props_check.py ALIGN.csv
"""
import sys, bisect, collections
sys.path.insert(0, 'scripts/hunt')
from lib import *
F = list(csv.DictReader(open('data/functions.csv')))
starts = sorted(int(r['wp2_entry'], 16) & ~1 for r in F); size = {int(r['wp2_entry'], 16) & ~1: int(r['size']) for r in F}
def fn_of(a): return starts[bisect.bisect_right(starts, a) - 1]
API2 = {int(amap[n]['wp2_addr'], 16) & ~1: n for n in ('UX2SYS_GET', 'UX2SYS_SET', 'UX2SYS_SET_LEN')}
API3 = {int(amap[n]['wp3_addr'], 16) & ~1: n for n in ('UX2SYS_GET', 'UX2SYS_SET', 'UX2SYS_SET_LEN')}
def r0_before(img, site):
    """immediate last moved into r0 in the 8 halfwords before a call, or None"""
    for back in range(2, 18, 2):
        a = site - back
        i = next(cs.disasm(img[a - BASE:a - BASE + 4], a), None)
        if i is None: continue
        if i.size != 2 and back < 4: continue
        m = re.match(r'r0, #(0x[0-9a-f]+|\d+)$', i.op_str)
        if i.mnemonic in ('movs', 'mov', 'mov.w', 'movw') and m: return int(m[1], 0)
        if re.match(r'r0,', i.op_str) and i.mnemonic not in ('cmp', 'tst', 'str', 'strb', 'strh', 'cbz', 'cbnz'): return None
    return None
def sites(img, api):
    out = []
    for t, name in api.items():
        for c in callers(img, t): out.append((c, name, r0_before(img, c)))
    return sorted(out)
s2 = sites(A, API2); s3 = sites(B, API3)
by2 = collections.defaultdict(list)
for c, n, v in s2: by2[fn_of(c)].append((c, n, v))
s3addr = [c for c, _, _ in s3]
votes = collections.Counter()
for f, lst in by2.items():
    t = twin.get(f)
    if not t: continue
    lo = bisect.bisect_left(s3addr, t); hi = bisect.bisect_left(s3addr, t + int(size[f] * 1.4) + 32)
    l3 = s3[lo:hi]
    if len(l3) != len(lst) or [n for _, n, _ in l3] != [n for _, n, _ in lst]: continue
    for (c2, n, v2), (c3, _, v3) in zip(lst, l3):
        if v2 is not None and v3 is not None: votes[(v2, v3)] += 1
align = {}
for r in csv.DictReader(open(sys.argv[1])):
    if r['wp2_id'] and r['wp3_id']: align[int(r['wp2_id'], 16)] = (int(r['wp3_id'], 16), r['evidence'])
print('wp2 call sites with a constant id: %d of %d; wp3: %d of %d' % (sum(v is not None for _, _, v in s2), len(s2), sum(v is not None for _, _, v in s3), len(s3)))
agree = disagree = 0; seen = collections.defaultdict(collections.Counter)
for (v2, v3), n in votes.items(): seen[v2][v3] += n
for v2 in sorted(seen):
    exp = align.get(v2, (None, ''))
    top = seen[v2].most_common()
    ok = exp[0] == top[0][0]
    agree += ok; disagree += (not ok)
    print('  0x%02x -> %s   alignment says %s (%s)  %s' % (v2, ', '.join('0x%02x x%d' % (a, n) for a, n in top), ('0x%02x' % exp[0]) if exp[0] is not None else 'none', exp[1], 'OK' if ok else 'DIFFERENT'))
print('ids checked: %d, agree: %d, differ: %d' % (agree + disagree, agree, disagree))
