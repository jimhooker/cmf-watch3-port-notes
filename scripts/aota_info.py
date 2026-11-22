#!/usr/bin/env python3
"""Minimal AOTA inspector/unpacker written from the documented container layout.

usage: aota_info.py IMAGE [OUTDIR]
"""
import lzma
import struct
import sys
import zlib
from pathlib import Path


def hexdump(b, base=0, width=16):
    out = []
    for i in range(0, len(b), width):
        chunk = b[i:i + width]
        hx = " ".join(f"{c:02x}" for c in chunk)
        asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
        out.append(f"{base + i:08x}  {hx:<{width * 3}} {asc}")
    return "\n".join(out)


def parse(data):
    assert data[:4] == b"AOTA", data[:4]
    entries = []
    for i in range(16):
        off = 0x200 + i * 32
        e = data[off:off + 32]
        name = e[:12].split(b"\0")[0].decode("ascii", "replace")
        if not name:
            continue
        words = struct.unpack_from("<5I", e, 12)
        entries.append((name, words, e))
    return entries


def unlzma_chunks(blob):
    """b'LZMA', u32 16, u32 packed, u32 size, then an XZ stream; repeated."""
    out = bytearray()
    pos = 0
    n = 0
    while pos + 16 <= len(blob) and blob[pos:pos + 4] == b"LZMA":
        hdr, packed, size = struct.unpack_from("<3I", blob, pos + 4)
        body = blob[pos + hdr:pos + hdr + packed]
        raw = lzma.decompress(body)
        assert len(raw) == size, (len(raw), size)
        out += raw
        pos += hdr + packed
        n += 1
    return bytes(out), n, pos


def main():
    img = Path(sys.argv[1]).read_bytes()
    outdir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    print("size", len(img))
    print(hexdump(img[:0xA0]))
    print("version_name", img[0x40:0x60].split(b"\0")[0], "board", img[0x60:0x80].split(b"\0")[0])
    entries = parse(img)
    for name, words, raw in entries:
        print(f"{name:<14}", " ".join(f"{w:#010x}" for w in words))
    if outdir is None:
        return
    outdir.mkdir(parents=True, exist_ok=True)
    for name, words, raw in entries:
        # layout guess: rsv, offset, length, rsv/orig, crc -> find the pair that fits
        cands = [(words[i], words[j]) for i in range(5) for j in range(5) if i != j]
        best = None
        for off, ln in cands:
            if 0x400 <= off < len(img) and 0 < ln <= len(img) - off:
                blob = img[off:off + ln]
                if (zlib.crc32(blob) & 0xFFFFFFFF) in words:
                    best = (off, ln)
                    break
        if best is None:
            print("!! no crc-consistent (offset,length) for", name)
            continue
        off, ln = best
        blob = img[off:off + ln]
        (outdir / name).write_bytes(blob)
        print(f"wrote {name} off={off:#x} len={ln:#x} magic={blob[:4]!r}")
        if blob[:4] == b"LZMA":
            raw_, n, used = unlzma_chunks(blob)
            (outdir / (name + ".unlzma")).write_bytes(raw_)
            print(f"   lzma chunks={n} used={used:#x} -> {len(raw_)} bytes magic={raw_[:4]!r}")


if __name__ == "__main__":
    main()
