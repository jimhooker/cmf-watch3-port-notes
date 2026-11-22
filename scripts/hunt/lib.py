"""Search helpers for hunting addresses by hand: BL callers, literal-pool words, masked byte patterns, literal loads
and string anchors. Run from the project root; reads work/wp2/app_073.bin and work/wp3-inner/app.bin. Static only.
"""
import struct,csv,re
from capstone import *
BASE=0x10000000
A=open('work/wp2/app_073.bin','rb').read(); B=open('work/wp3-inner/app.bin','rb').read()
cs=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS|CS_MODE_V8)
CODE_END=0x260000
def w(img,a): return struct.unpack_from('<I',img,a-BASE)[0]
def bl_target(img,off):
    h1,h2=struct.unpack_from('<HH',img,off)
    if (h1&0xf800)!=0xf000 or (h2&0xd000)!=0xd000: return None
    s=(h1>>10)&1; j1=(h2>>13)&1; j2=(h2>>11)&1
    i1=1-(j1^s); i2=1-(j2^s)
    imm=(s<<24)|(i1<<23)|(i2<<22)|((h1&0x3ff)<<12)|((h2&0x7ff)<<1)
    if s: imm-=1<<25
    return BASE+off+4+imm
_cache={}
def all_bl(img):
    k=id(img)
    if k not in _cache:
        d={}
        for off in range(0x200,min(len(img)-4,CODE_END),2):
            t=bl_target(img,off)
            if t is not None and BASE<=t<BASE+CODE_END: d.setdefault(t&~1,[]).append(BASE+off)
        _cache[k]=d
    return _cache[k]
def callers(img,target): return all_bl(img).get(target&~1,[])
def words(img,val,lo=0,hi=None):
    pat=struct.pack('<I',val); out=[]; i=lo
    while True:
        i=img.find(pat,i,hi or len(img))
        if i<0: break
        if i%4==0: out.append(BASE+i)
        i+=1
    return out
def dis(img,a,n=12):
    out=[]
    for i in cs.disasm(img[a-BASE:a-BASE+n*4],a):
        out.append('%08x %-7s %s'%(i.address,i.mnemonic,i.op_str))
        if len(out)>=n: break
    return out
def lit(img,a,disp): return w(img,((a+4)&~3)+disp)
amap={r['name']:r for r in csv.DictReader(open('data/address-map.csv'))}
twin={}; rtwin={}
for r in csv.DictReader(open('data/functions.csv')):
    if r['wp3_entry']:
        twin[int(r['wp2_entry'],16)&~1]=int(r['wp3_entry'],16)&~1; rtwin[int(r['wp3_entry'],16)&~1]=int(r['wp2_entry'],16)&~1
def find_masked(img,pattern,mask,lo=0x200,hi=CODE_END):
    out=[]; n=len(pattern)
    first=[i for i in range(n) if mask[i]==0xff]
    anchor=first[0]; b=pattern[anchor:anchor+1]
    # find longest fully-masked run for anchoring
    runs=[]; i=0
    while i<n:
        if mask[i]==0xff:
            j=i
            while j<n and mask[j]==0xff: j+=1
            runs.append((j-i,i)); i=j
        else: i+=1
    ln,st=max(runs); key=pattern[st:st+ln]
    pos=lo
    while True:
        pos=img.find(key,pos,hi)
        if pos<0: break
        s=pos-st
        if s>=0 and all((img[s+k]&mask[k])==(pattern[k]&mask[k]) for k in range(n)): out.append(BASE+s)
        pos+=2
    return out

def cstr(img,v,minlen=5):
    if not (BASE+0x1c0000<=v<BASE+len(img)): return None
    t=img[v-BASE:v-BASE+80].split(b'\0')[0]
    if len(t)>=minlen and all(32<=c<127 or c in(10,13,9) for c in t): return t.decode()
    return None
def lit_loads(img,lo,hi):
    """(addr, value) of every pc-relative ldr in [lo,hi), in address order, skipping literal pools"""
    out=[]; a=lo; pools=set()
    while a<hi:
        if a in pools: a+=4; continue
        i=next(cs.disasm(img[a-BASE:a-BASE+4],a),None)
        if i is None: a+=2; continue
        if i.mnemonic.startswith('ldr') and '[pc' in i.op_str:
            d=int(i.op_str.split('#')[1].rstrip(']'),16) if '#' in i.op_str else 0
            l=((a+4)&~3)+d
            if l-BASE+4<=len(img):
                pools.add(l); out.append((a,w(img,l)))
        a+=i.size
    return out
_strpos={}
def str_refs_wp3(s):
    """code literal-pool addresses in WP3 that hold a pointer to string s (exact, NUL-terminated, unique)"""
    key=s.encode()+b'\0'
    i=B.find(b'\0'+key)
    if i<0: return []
    if B.find(b'\0'+key,i+1)>=0: return []
    a=BASE+i+1
    return [r for r in words(B,a) if r<BASE+CODE_END]
def show_pair(lo2,hi2,pad=0x60):
    la=lit_loads(A,lo2,hi2)
    anchors=[]
    for a,v in la:
        s=cstr(A,v)
        if s:
            for r in str_refs_wp3(s): anchors.append(r)
    print('  WP2 %08x-%08x literal loads:'%(lo2,hi2))
    for a,v in la: print('     %08x  %08x %s'%(a,v,repr(cstr(A,v)) if cstr(A,v) else ''))
    if not anchors: print('  no string anchors in WP3'); return
    lo3=min(anchors)-(hi2-lo2)-pad; hi3=max(anchors)
    print('  WP3 anchors (literal pool slots) %08x..%08x; loads in %08x-%08x:'%(min(anchors),max(anchors),lo3,hi3))
    for a,v in lit_loads(B,lo3&~1,hi3):
        if 0x2ff00000<=v<0x38800000 or cstr(B,v): print('     %08x  %08x %s'%(a,v,repr(cstr(B,v)) if cstr(B,v) else ''))
