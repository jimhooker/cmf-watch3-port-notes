#!/usr/bin/env bash
# Build cmf-watch-sdk's Watch 3 Pro stub and patch it onto a stock 1.0.1.77 app.bin, without the SDK's own
# environment (no nix, no llvm-objcopy, no uv). Nothing here touches a watch: the result is for the emulator
# (EMU_APP=OUT scripts/emu_call.py ...).
#
# usage: scripts/wp3_stub_build.sh SDK_CHECKOUT STOCK_APP_BIN OUT_APP_BIN [lazy]
#
# With "lazy" the watch-face guard's calls stay stock, so no stub code runs until the app list is opened and the
# boot path is the stock one. The changed byte ranges are printed either way.
#
# Needs rustup with the thumbv7em-none-eabi target and binutils' objcopy. Prints the stub's hooks.
set -euo pipefail
SDK=$(cd "${1:?path to a cmf-watch-sdk checkout}" && pwd)
STOCK=$(realpath "${2:?stock Watch 3 Pro app.bin}")
OUT=$(realpath -m "${3:?output app.bin}")
MODE=${4:-guard}
(cd "$SDK/fw" && cargo build --release -p wp3-stub 2>&1 | grep -v "no-movt\|^ *|\|= note\|= help\|^$" || true)
mkdir -p "$SDK/target"
objcopy -I elf32-little -O binary "$SDK/fw/target/thumbv7em-none-eabi/release/wp3-stub" "$SDK/target/wp3-stub.bin"
PYTHONPATH="$SDK/src" python3 - "$STOCK" "$SDK/target/wp3-stub.bin" "$OUT" "$MODE" <<'PY'
import struct
import sys
from pathlib import Path

from wp2apps import firmware

stock, stub = Path(sys.argv[1]).read_bytes(), Path(sys.argv[2]).read_bytes()
version = struct.unpack_from("<I", stub, 4)[0]
hooks = struct.unpack_from("<%dI" % (5 if version == 1 else 7), stub, 8)
names = ("wf_boot", "wf_saved", "power_down", "forced_reboot", "wf_parse", "applist_list", "applist_grid")
if sys.argv[4] not in ("guard", "lazy"):
    sys.exit("the fourth argument is \"lazy\" or nothing")
out = firmware.patch_wp3(stock, stub, guard=sys.argv[4] == "guard")
Path(sys.argv[3]).write_bytes(out)
print("stub: %d bytes, header version %d" % (len(stub), version))
print(" ".join("%s=%08x" % pair for pair in zip(names, hooks)))
print("changed in the stock bytes:", ", ".join("%#x..%#x" % r for r in firmware.changed_ranges(stock, out[:len(stock)])))
print("appended: %#x..%#x" % (len(stock), len(out)))
PY
echo "$OUT"
