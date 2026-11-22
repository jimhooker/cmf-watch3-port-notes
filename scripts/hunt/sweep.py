"""Split a code range into functions by linear sweep and print them with known names.

usage (from the project root): scripts/hunt/sweep.py a|b LO HI   (a = Watch Pro 2 image, b = Watch 3 Pro image)
Works best in the literal-free region (0x101Cxxxx on the Watch Pro 2, 0x101Dxxxx-0x101Exxxx on the Watch 3 Pro).
"""
import struct,sys,re,csv
from capstone import *
BASE=0x10000000
cs=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS|CS_MODE_V8)
def names(side):
    n={}
    for r in csv.DictReader(open('data/functions.csv')):
        if side=='b' and r['wp3_entry']: n[int(r['wp3_entry'],16)&~1]='twin_%s'%r['wp2_entry'][2:]
        if side=='a': n[int(r['wp2_entry'],16)&~1]=('->'+r['wp3_entry'][2:] if r['wp3_entry'] else 'nomatch')+(' '+r['source_file'].split('/')[-1] if r['source_file'] else '')
    for r in csv.DictReader(open('data/address-map.csv')):
        k='wp3_addr' if side=='b' else 'wp2_addr'
        if r[k].startswith('0x'): n[int(r[k],16)&~1]=r['name']+((' ->'+r['wp3_addr'][2:]) if side=='a' and r['wp3_addr'] else '')
    try:
        for l in open('work/hunt/found.tsv'):
            p=l.split()
            if side=='b' and len(p)>=2: n[int(p[1],16)&~1]=p[0]
    except FileNotFoundError: pass
    return n
def split(img,lo,hi):
    """linear sweep, returns list of functions [(start,[ins])]"""
    funcs=[]; cur=[]; far=0; a=lo
    while a<hi:
        ins=next(cs.disasm(img[a-BASE:a-BASE+4],a),None)
        if ins is None:
            cur.append((a,'.short','%04x'%struct.unpack_from('<H',img,a-BASE)[0])); a+=2; continue
        mn,ops=ins.mnemonic,ins.op_str
        cur.append((a,mn,ops))
        tgt=None
        m=re.search(r'#0x([0-9a-f]+)$',ops)
        if m and (mn.startswith('b') and mn not in('bl','blx','bic','bics','bfi','bfc','bx','bic.w','bics.w') or mn in('cbz','cbnz')):
            tgt=int(m[1],16)
        start=cur[0][0]
        term=(mn in('pop','pop.w') and 'pc' in ops) or mn=='bx' or mn in('b','b.w') 
        if tgt and start<=tgt and tgt>a and tgt-a<0x800 and not (mn in('b','b.w') and tgt-a>0x400): far=max(far,tgt)
        a+=ins.size
        if term and far<a:
            funcs.append((start,cur)); cur=[]; far=0
    if cur: funcs.append((cur[0][0],cur))
    return funcs
def fmt(f,n):
    out=[]
    for a,mn,ops in f[1]:
        note=''
        m=re.match(r'#0x([0-9a-f]+)$',ops)
        if m and mn in('bl','b','b.w'):
            t=int(m[1],16)
            if t in n: note='  <%s>'%n[t]
        out.append('%08x %-7s %s%s'%(a,mn,ops,note))
    return out
if __name__=='__main__':
    side=sys.argv[1]; img=open('work/wp2/app_073.bin' if side=='a' else 'work/wp3-inner/app.bin','rb').read()
    lo,hi=int(sys.argv[2],16),int(sys.argv[3],16); n=names(side)
    for f in split(img,lo,hi):
        print('--- fn %08x (%d bytes) %s'%(f[0],f[1][-1][0]-f[0]+2,n.get(f[0],'')))
        print('\n'.join(fmt(f,n)))
