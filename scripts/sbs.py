#!/usr/bin/env python3
"""side-by-side disassembly: sbs.py A_APP B_APP A_ADDR B_ADDR [N]"""
import sys
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS, CS_MODE_V8
BASE=0x10000000
cs=Cs(CS_ARCH_ARM, CS_MODE_THUMB|CS_MODE_MCLASS|CS_MODE_V8)
A=open(sys.argv[1],"rb").read(); B=open(sys.argv[2],"rb").read()
pairs=sys.argv[3:]
n=14
if len(pairs)%2: n=int(pairs[-1]); pairs=pairs[:-1]
def dis(img,a,n):
    o=(a&~1)-BASE; out=[]
    for i,(ad,sz,m,ops) in enumerate(cs.disasm_lite(img[o:o+n*4+8],a&~1)):
        out.append("%08x %-7s %s"%(ad,m,ops))
        if i+1>=n: break
    return out
for i in range(0,len(pairs),2):
    a=int(pairs[i],16); b=int(pairs[i+1],16)
    la=dis(A,a,n); lb=dis(B,b,n)
    print("== A %#x  |  B %#x"%(a,b))
    for j in range(max(len(la),len(lb))):
        x=la[j] if j<len(la) else ""; y=lb[j] if j<len(lb) else ""
        print("  %-44s | %s"%(x[:44],y[:44]))
