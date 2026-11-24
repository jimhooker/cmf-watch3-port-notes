#!/usr/bin/env python3
"""Build a Watch 3 Pro update package that carries a patched app.bin, and check it against the official one.
Offline only: nothing here talks to a watch, and the result must not be flashed without the watch owner's explicit approval.

usage: scripts/wp3_ota_build.py SDK_CHECKOUT UTILS_CHECKOUT OFFICIAL_PACKAGE APP_BIN OUT_PACKAGE

The steps are those of cmf-watch-sdk's `wp2apps ota-image` (src/wp2apps/cli.py, ota_image), run without the SDK's
own environment: its byte helpers are imported from SDK_CHECKOUT/src and `fwkit` is run as an external tool in
UTILS_CHECKOUT. Nothing but app.bin, its manifest entry and the checksums that cover them is changed; the version
fields stay as they are.

Then it checks, with its own parser, that the result differs from the official package only where it must:
  - outer package: same entries in the same order; every part except ota.xml and TEMP.bin is byte-identical;
  - outer ota.xml: only TEMP.bin's file_size, orig_size and checksum differ;
  - inside TEMP.bin: app.bin is APP_BIN, every other part is byte-identical, and in the inner ota.xml only
    app.bin's file_size, orig_size and checksum differ;
  - every CRC32 in both containers holds.
Give the stock app.bin as APP_BIN to prove the builder: the result must then equal the official package exactly.
"""
import hashlib
import lzma
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path


def entries(image):
    """[(name, offset, length, crc)] of an AOTA container, after checking its header and data CRCs."""
    if image[:4] != b"AOTA":
        sys.exit("not an AOTA container")
    start, end = struct.unpack_from("<H", image, 0x12)[0], struct.unpack_from("<I", image, 0x14)[0]
    if zlib.crc32(image[0x08:0x400]) != struct.unpack_from("<I", image, 0x04)[0]:
        sys.exit("header CRC mismatch")
    if zlib.crc32(image[start:end]) != struct.unpack_from("<I", image, 0x18)[0]:
        sys.exit("data CRC mismatch")
    out = []
    for i in range(16):
        entry = image[0x200 + 32 * i:0x220 + 32 * i]
        name = entry[:12].split(b"\0")[0].decode()
        if not name:
            continue
        offset, length = struct.unpack_from("<II", entry, 16)
        crc = struct.unpack_from("<I", entry, 28)[0]
        if zlib.crc32(image[offset:offset + length]) != crc:
            sys.exit("CRC mismatch in %s" % name)
        out.append((name, offset, length, crc))
    return out


def parts(image):
    return {name: image[offset:offset + length] for name, offset, length, _ in entries(image)}


def unchunk(stored):
    """TEMP.bin as stored: chunks of b"LZMA", u32 16, u32 packed size, u32 size, then an XZ stream."""
    out, at = bytearray(), 0
    while at < len(stored):
        magic, head, packed, size = struct.unpack_from("<4sIII", stored, at)
        if magic != b"LZMA" or head != 16:
            sys.exit("TEMP.bin is not stored as LZMA chunks")
        piece = lzma.decompress(stored[at + 16:at + 16 + packed], format=lzma.FORMAT_XZ)
        if len(piece) != size:
            sys.exit("TEMP.bin chunk has the wrong length")
        out += piece
        at += 16 + packed
    return bytes(out)


def manifest(xml):
    """(leaf fields before the first partition, {file_name: fields}, the text with every value blanked)."""
    text = xml.decode()
    leaf = r"<(\w+)>([^<]*)</\1>"
    partitions = {}
    for block in re.findall(r"<partition>.*?</partition>", text, re.S):
        fields = dict(re.findall(leaf, block))
        partitions[fields["file_name"]] = fields
    return dict(re.findall(leaf, text.split("<partition>")[0])), partitions, re.sub(r">[^<]*<", "><", text)


def xml_changes(old, new):
    """(partition file name or None, tag) of every field that differs between two manifests."""
    (old_head, old_parts, old_shape), (new_head, new_parts, new_shape) = manifest(old), manifest(new)
    if old_shape != new_shape or list(old_parts) != list(new_parts):
        sys.exit("ota.xml changed its structure")
    out = {(None, tag) for tag in old_head if old_head[tag] != new_head[tag]}
    for name, fields in old_parts.items():
        out |= {(name, tag) for tag in fields if fields[tag] != new_parts[name][tag]}
    return out


def main():
    if len(sys.argv) != 6:
        sys.exit(__doc__)
    sdk, utils, official, app_path, out_path = (Path(p).resolve() for p in sys.argv[1:])
    sys.path.insert(0, str(sdk / "src"))
    from wp2apps import firmware  # noqa: E402  (pure byte helpers; no Bluetooth modules)

    def fwkit(*args):
        done = subprocess.run(["uv", "run", "fwkit", *map(str, args)], cwd=utils, capture_output=True, text=True)
        if done.returncode:
            sys.exit("fwkit %s failed: %s" % (args[0], (done.stderr or done.stdout).strip()))
        return done.stdout

    stock_image, app = official.read_bytes(), app_path.read_bytes()
    firmware.check_acth(app)
    if out_path.exists():
        sys.exit("%s exists" % out_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        outer, inner, temp, built = tmp / "outer", tmp / "inner", tmp / "TEMP.bin", tmp / "out.bin"
        fwkit("unpack", official, outer)
        fwkit("unpack", "--no-raw", outer / "raw/TEMP.bin.bin", inner)
        (inner / "parts/app.bin.part").write_bytes(app)
        xml = inner / "ota.xml"
        xml.write_bytes(firmware.ota_xml_set(xml.read_bytes().decode(), "app.bin", file_size=len(app),
                                             orig_size=len(app), checksum=zlib.crc32(app)).encode())
        fwkit("pack", inner, temp)
        stored = firmware.xz_chunks(firmware.fix_aota_crc(temp.read_bytes()))
        (outer / "parts/TEMP.bin.part").write_bytes(stored)
        xml = outer / "ota.xml"
        xml.write_bytes(firmware.ota_xml_set(xml.read_bytes().decode(), "TEMP.bin", file_size=len(stored),
                                             orig_size=len(stored), checksum=zlib.crc32(stored)).encode())
        fwkit("pack", outer, built)
        image = firmware.fix_aota_crc(built.read_bytes())
        built.write_bytes(image)
        print("fwkit verify:", fwkit("verify", built).strip().splitlines()[-1])

    # the checks below use this script's own parser, not fwkit
    old, new = parts(stock_image), parts(image)
    if [e[0] for e in entries(stock_image)] != [e[0] for e in entries(image)]:
        sys.exit("the outer directory changed")
    changed = [name for name in old if old[name] != new[name]]
    print("outer parts that differ:", ", ".join(changed) or "none")
    if not set(changed) <= {"ota.xml", "TEMP.bin"}:
        sys.exit("a part other than ota.xml and TEMP.bin changed")
    outer_xml = xml_changes(old["ota.xml"], new["ota.xml"])
    print("outer ota.xml fields that differ:", sorted(outer_xml) or "none")
    if not outer_xml <= {("TEMP.bin", tag) for tag in ("file_size", "orig_size", "checksum")}:
        sys.exit("the outer ota.xml changed outside TEMP.bin's size and checksum")
    old_temp, new_temp = unchunk(old["TEMP.bin"]), unchunk(new["TEMP.bin"])
    old_in, new_in = parts(old_temp), parts(new_temp)
    if list(old_in) != list(new_in):
        sys.exit("the inner directory changed")
    changed = [name for name in old_in if old_in[name] != new_in[name]]
    print("parts inside TEMP.bin that differ:", ", ".join(changed) or "none")
    if not set(changed) <= {"ota.xml", "app.bin"} or new_in["app.bin"] != app:
        sys.exit("TEMP.bin does not carry exactly this app.bin with the other parts unchanged")
    inner_xml = xml_changes(old_in["ota.xml"], new_in["ota.xml"])
    print("inner ota.xml fields that differ:", sorted(inner_xml) or "none")
    if not inner_xml <= {("app.bin", tag) for tag in ("file_size", "orig_size", "checksum")}:
        sys.exit("the inner ota.xml changed outside app.bin's size and checksum")
    for label, xml_bytes, container in (("outer", new["ota.xml"], new), ("inner", new_in["ota.xml"], new_in)):
        for name, fields in manifest(xml_bytes)[1].items():
            if int(fields["file_size"], 16) != len(container[name]):
                sys.exit("%s ota.xml: file_size of %s does not match the part" % (label, name))
    print("TEMP.bin: %#x bytes stored (official %#x), %#x unpacked (official %#x)"
          % (len(new["TEMP.bin"]), len(old["TEMP.bin"]), len(new_temp), len(old_temp)))
    print("app.bin: %#x bytes (official %#x), sha256 %s" % (len(app), len(old_in["app.bin"]),
                                                             hashlib.sha256(app).hexdigest()[:16]))
    print("identical to the official package" if image == stock_image else
          "differs from the official package (%#x bytes, official %#x)" % (len(image), len(stock_image)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(image)
    print("wrote %s, sha256 %s" % (out_path, hashlib.sha256(image).hexdigest()))


if __name__ == "__main__":
    main()
