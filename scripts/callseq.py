"""Compare call sequences and struct offsets of the two sides of fn_pair.py dumps.

usage: callseq.py REVIEW_DIR NAME [NAME ...]   (REVIEW_DIR is the OUT_DIR given to fn_pair.py). Static analysis only.
"""
import re,sys,csv
from pathlib import Path
ASSERT={'1013a098','101ba194','100eeb30','101c54c2','1014c818'}
ASSERT3={'101480d8','101d7252','100eefd8','101590b8'}
def parse(lines):
    out=[]
    for l in lines:
        m=re.match(r'([0-9a-f]{8}) (\S+)\s+(.*)',l)
        if m: out.append((int(m[1],16),m[2],m[3]))
    return out
def body(ins):
    # cut at function end: terminal instruction with no pending forward branch
    far=0; res=[]
    for a,mn,ops in ins:
        res.append((a,mn,ops))
        t=re.match(r'#0x([0-9a-f]+)',ops) if mn.startswith(('b','cb')) and mn not in('bl','blx','bic','bics','bfi','bfc','bx') else None
        if mn in('cbz','cbnz'): t=re.search(r'#0x([0-9a-f]+)',ops)
        tgt=int(t[1],16) if t else None
        term = (mn in('pop','pop.w') and 'pc' in ops) or (mn=='bx') or (mn in('b','b.w'))
        if tgt and mn not in('b','b.w') : far=max(far,tgt)
        if mn in('b','b.w') and tgt and ins[0][0]<=tgt<=a+0x400 and tgt>a: far=max(far,tgt)
        if term and far<=a: break
    return res
def calls(ins,skip):
    c=[]
    for a,mn,ops in ins:
        if mn in('bl','b.w','b') :
            m=re.match(r'#0x([0-9a-f]+)(.*)',ops)
            if not m: continue
            t=m[1]
            if mn!='bl' and ins[0][0]<=int(t,16)<=ins[-1][0]: continue
            if t in skip: continue
            c.append((t,m[2].strip()))
    return c
def offs(ins):
    s=set()
    for a,mn,ops in ins:
        for m in re.finditer(r'\[(r\d+|sb|sl|fp), #(0x[0-9a-f]+|\d+)\]',ops):
            s.add(int(m[2],0))
    return sorted(s)
def consts(ins):
    s=[]
    for a,mn,ops in ins:
        if mn in('cmp','movs','mov.w','tst','tst.w','ands','and','orr','bic','mov','movw','cmp.w') :
            m=re.search(r'#(0x[0-9a-f]+|\d+)$',ops)
            if m: s.append(int(m[1],0))
    return s
REVIEW=Path(sys.argv[1])
for name in sys.argv[2:]:
    t=(REVIEW/('%s.txt'%name)).read_text().split('## Watch 3 Pro')
    a=body(parse(t[0].splitlines())); b=body(parse(t[1].splitlines()))
    ca=calls(a,ASSERT); cb=calls(b,ASSERT3)
    print('=====',name,'wp2 ins',len(a),'wp3 ins',len(b))
    ta=[re.search(r'wp3 ([0-9a-f]{8})',x[1]) for x in ca]
    ta=[(m[1] if m else '?'+x[0]) for m,x in zip(ta,ca)]
    tb=[x[0] for x in cb]
    print(' wp2 calls→wp3:',' '.join(ta)); print(' wp3 calls     :',' '.join(tb)); print(' SAME CALLS' if ta==tb else ' calls differ')
    print(' wp2 offsets',[hex(x) for x in offs(a)]); print(' wp3 offsets',[hex(x) for x in offs(b)])
