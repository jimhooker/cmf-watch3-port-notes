"""List every LVGL widget class table in both images, starting from lv_obj_class, and cross-match them.

usage (from the project root): scripts/hunt/classes.py
"""
import struct,sys,csv
BASE=0x10000000
A=open('work/wp2/app_073.bin','rb').read(); B=open('work/wp3-inner/app.bin','rb').read()
def w(img,a): return struct.unpack_from('<I',img,a-BASE)[0]
def rec(img,a): return struct.unpack_from('<8I',img,a-BASE)
def iscode(img,p): return p==0 or (p&1 and BASE+0x200<=p<BASE+0x260000)
def find_classes(img,root):
    found={root:None}; todo=[root]
    while todo:
        base=todo.pop()
        pat=struct.pack('<I',base); i=0
        while True:
            i=img.find(pat,i)
            if i<0: break
            if i%4==0 and i+32<=len(img):
                r=struct.unpack_from('<8I',img,i)
                a=BASE+i
                inst=(r[7]>>4)&0xffff
                if a not in found and iscode(img,r[1]) and iscode(img,r[2]) and iscode(img,r[4]) and r[3]==0 and 0x20<=inst<0x400 and (r[7]>>20)==0 and (r[1] or r[2] or r[4]):
                    found[a]=base; todo.append(a)
            i+=4
    return found
if __name__=='__main__':
    print('wp2 lv_obj_class',[hex(x) for x in rec(A,0x101fb27c)])
    ca=find_classes(A,0x101fb27c)
    print('wp2 classes',len(ca))
    # wp3 root: search record with base 0, inst 0x30, same width/height/bits as wp2 root
    r2=rec(A,0x101fb27c)
    cands=[]
    for i in range(0,len(B)-32,4):
        r=struct.unpack_from('<8I',B,i)
        if r[0]==0 and r[3]==0 and r[5]==r2[5] and r[6]==r2[6] and (r[7]&0xf)==(r2[7]&0xf) and ((r[7]>>4)&0xffff)==0x30 and all(iscode(B,x) and x for x in (r[1],r[2],r[4])):
            cands.append(BASE+i)
    print('wp3 root candidates',[hex(c) for c in cands])
    cb=find_classes(B,0x10230078)
    print('wp3 classes',len(cb))
    names={}
    for r in csv.DictReader(open('data/address-map.csv')):
        if r['name'].endswith('_CREATE') and r['kind']=='function':
            a=int(r['wp2_addr'],16)&~1
            # literal after 20-byte create fn
            for off in range(8,40,4):
                v=w(A,(a&~3)+off)
                if v in ca: names[v]=r['name'][:-7]; break
    twin={}
    for r in csv.DictReader(open('data/functions.csv')):
        if r['wp3_entry']: twin[int(r['wp2_entry'],16)&~1]=int(r['wp3_entry'],16)&~1
    def show(img,cls,nm):
        for a in sorted(cls):
            r=rec(img,a)
            print('  %08x base=%08x ctor=%08x dtor=%08x ev=%08x w=%x h=%x ed/grp=%x inst=%#x %s'%(a,r[0],r[1],r[2],r[4],r[5],r[6],r[7]&0xf,(r[7]>>4)&0xffff,nm.get(a,'')))
    print('WP2'); show(A,ca,names)
    # map classes by twin ctor/dtor/event
    m3={}
    for a in ca:
        r=rec(A,a)
        want=[twin.get(x&~1) for x in (r[1],r[2],r[4]) if x]
        for b in cb:
            rb=rec(B,b)
            have={x&~1 for x in (rb[1],rb[2],rb[4]) if x}
            if any(t in have for t in want if t): m3.setdefault(b,[]).append(names.get(a,hex(a)))
    print('WP3'); show(B,cb,{b:'<= '+','.join(v) for b,v in m3.items()})
