#!/usr/bin/env python3
"""Emulator rehearsal only: cut a Watch 3 Pro update package down to its manifest and TEMP.bin.

usage: scripts/wp3_ota_temponly.py SDK_CHECKOUT UTILS_CHECKOUT FULL_PACKAGE OUT_PACKAGE

cmf-watch-utils' `emu ota` accepts only an outer container that holds TEMP.bin alone (emu/image.py,
verify_package). TEMP.bin carries app.bin and sdfs.bin; the six resource files next to it in a full package are
stock and unchanged by our build. This keeps the header, the stored TEMP.bin bytes and TEMP.bin's manifest entry
exactly as they are, drops the other parts and their manifest entries, and sets partitionsNum to 1.

The result is for the emulator. It is not the package for a real watch: that is FULL_PACKAGE.
"""
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path


def stored_parts(image):
    """{name: stored bytes} of an AOTA container, in directory order."""
    count = struct.unpack_from("<I", image, 0x0C)[0]
    out = {}
    for i in range(count):
        entry = image[0x200 + 32 * i:0x220 + 32 * i]
        name = entry[:16].split(b"\0")[0].decode()
        offset, length = struct.unpack_from("<II", entry, 16)
        out[name] = image[offset:offset + length]
    return out


def main():
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    sdk, utils, full, out_path = (Path(p).resolve() for p in sys.argv[1:])
    sys.path.insert(0, str(sdk / "src"))
    from wp2apps import firmware  # noqa: E402  (pure byte helpers)

    if out_path.exists():
        sys.exit("%s exists" % out_path)
    image = full.read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        unpack = subprocess.run(["uv", "run", "fwkit", "unpack", "--no-raw", str(full), str(tmp / "pkg")],
                                cwd=utils, capture_output=True, text=True)
        if unpack.returncode:
            sys.exit("fwkit unpack failed: %s" % unpack.stderr.strip())
        pkg = tmp / "pkg"
        hdr = bytearray((pkg / "hdr.bin").read_bytes())
        table = hdr[0x200:0x400]
        names = [table[32 * i:32 * i + 16].split(b"\0")[0].decode() for i in range(struct.unpack_from("<I", hdr, 0x0C)[0])]
        if names[:2] != ["ota.xml", "TEMP.bin"]:
            sys.exit("unexpected directory order: %s" % names)
        hdr[0x200:0x400] = table[:64] + bytes(0x200 - 64)
        struct.pack_into("<I", hdr, 0x0C, 2)
        (pkg / "hdr.bin").write_bytes(hdr)

        xml = (pkg / "ota.xml").read_text()
        blocks = re.findall(r"\s*<partition>.*?</partition>", xml, re.S)
        keep = [b for b in blocks if "<file_name>TEMP.bin</file_name>" in b]
        if len(keep) != 1:
            sys.exit("TEMP.bin manifest entry not found exactly once")
        for block in blocks:
            if block is not keep[0]:
                xml = xml.replace(block, "", 1)
        xml, n = re.subn(r"<partitionsNum>\d+</partitionsNum>", "<partitionsNum>1</partitionsNum>", xml)
        if n != 1:
            sys.exit("partitionsNum not found exactly once")
        (pkg / "ota.xml").write_text(xml)

        pack = subprocess.run(["uv", "run", "fwkit", "pack", str(pkg), str(tmp / "out.bin")],
                              cwd=utils, capture_output=True, text=True)
        if pack.returncode:
            sys.exit("fwkit pack failed: %s" % pack.stderr.strip())
        cut = firmware.fix_aota_crc((tmp / "out.bin").read_bytes())

    full_parts, cut_parts = stored_parts(image), stored_parts(cut)
    if list(cut_parts) != ["ota.xml", "TEMP.bin"] or cut_parts["TEMP.bin"] != full_parts["TEMP.bin"]:
        sys.exit("the cut package does not carry the full package's TEMP.bin unchanged")
    print("TEMP.bin identical to the full package's: %#x bytes, crc32 %#010x"
          % (len(cut_parts["TEMP.bin"]), zlib.crc32(cut_parts["TEMP.bin"])))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(cut)
    print("wrote %s (%d bytes)" % (out_path, len(cut)))


if __name__ == "__main__":
    main()
