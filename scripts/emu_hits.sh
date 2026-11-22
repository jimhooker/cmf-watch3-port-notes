#!/usr/bin/env bash
# Boot stock Watch 3 Pro firmware in the emulator and record which candidate addresses in data/address-map.csv
# are actually called. Emulator only; nothing touches a watch.
#
# usage: scripts/emu_hits.sh PATH_TO_cmf-watch-utils WORK_DIR [SECONDS] [RUN_NAME]
#
# Set ADDR_MAP=other.csv to probe a different table with the same columns (name, kind, wp3_addr).
# WORK_DIR must already hold runtime/ (QEMU + compat.bin), fixtures-wp3/ and an Arm-capable gdb at
# gdb/root/usr/bin/gdb-multiarch (or set GDB=...). Output: WORK_DIR/runs/RUN_NAME/hits.csv
set -euo pipefail
UTILS=$(cd "${1:?path to a cmf-watch-utils checkout}" && pwd)
WORK=$(cd "${2:?work dir}" && pwd)
SECS=${3:-60}
NAME=${4:-wp3-hits}
HERE=$(cd "$(dirname "$0")/.." && pwd)
GDB=${GDB:-$WORK/gdb/root/usr/bin/gdb-multiarch}
PORT=${EMU_GDB_PORT:-27777}
RUN=$WORK/runs/$NAME
[ ! -e "$RUN" ] || { echo "$RUN exists; pick another RUN_NAME" >&2; exit 1; }

(cd "$UTILS" && exec uv run cmf-watch-utils emu run --profile wp3-stock --fixtures "$WORK/fixtures-wp3" \
  --qemu "$WORK/runtime/qemu-system-arm" --rom "$WORK/runtime/compat.bin" --headless --seconds "$SECS" \
  --allow-reboot --watch-face-preview --gdb-port "$PORT" --output "$RUN") > "$WORK/runs/$NAME.emu.log" 2>&1 &
EMU=$!
for _ in $(seq 60); do
  (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null && break
  kill -0 "$EMU" 2>/dev/null || { echo "emulator exited early; see $WORK/runs/$NAME.emu.log" >&2; exit 1; }
  sleep 0.25
done
EMU_GDB_PORT=$PORT EMU_ADDR_MAP=${ADDR_MAP:-$HERE/data/address-map.csv} EMU_HITS_OUT=$RUN/hits.csv \
  "$GDB" -q -batch -x "$HERE/scripts/emu_hits_gdb.py" 2>&1 | tail -5
wait "$EMU" || true
echo "hits written to $RUN/hits.csv"
