#!/usr/bin/env bash
# Rebuild everything in data/ from the public reference firmware. Static analysis only; nothing touches a watch.
#
# usage: scripts/run_all.sh PATH_TO_cmf-watch-sdk PATH_TO_cmf-watch-utils [WORK_DIR]
#
# Needs: python3 with capstone and numpy (pip install capstone numpy), curl.
# The two reference images are the ones cmf-watch-utils publishes; they are downloaded into WORK_DIR and
# must never be committed (upstream rule: no firmware binaries in commits).
set -euo pipefail
SDK=${1:?path to a cmf-watch-sdk checkout}
UTILS=${2:?path to a cmf-watch-utils checkout}
WORK=${3:-work}
HERE=$(cd "$(dirname "$0")/.." && pwd)
PY=${PYTHON:-python3}
BASE=https://media.githubusercontent.com/media/fmctools/cmf-watch-utils/main/dumps/binaries
mkdir -p "$WORK/wp2" "$WORK/wp3"

[ -f "$WORK/wp2/app_073.bin" ] || curl -fL -o "$WORK/wp2/app_073.bin" "$BASE/app/app_073.bin"
[ -f "$WORK/wp3/JX402_w3pro_V1.0.1.77.bin" ] || curl -fL -o "$WORK/wp3/JX402_w3pro_V1.0.1.77.bin" "$BASE/firmware/JX402_w3pro_V1.0.1.77.bin"

# Watch 3 Pro: outer AOTA -> TEMP.bin (LZMA chunks) -> inner AOTA -> app.bin
$PY "$HERE/scripts/aota_info.py" "$WORK/wp3/JX402_w3pro_V1.0.1.77.bin" "$WORK/wp3-outer" > "$WORK/aota-outer.log"
$PY "$HERE/scripts/aota_info.py" "$WORK/wp3-outer/TEMP.bin.unlzma" "$WORK/wp3-inner" > "$WORK/aota-inner.log"

$PY "$HERE/scripts/collect_addrs.py" "$SDK" "$WORK/sdk_addrs.json"
$PY "$HERE/scripts/match.py" "$WORK/wp2/app_073.bin" "$WORK/wp3-inner/app.bin" \
  "$UTILS/dumps/analysis/function_map.tsv" "$WORK/sdk_addrs.json" "$WORK/match.json"
$PY "$HERE/scripts/srcmap.py" "$WORK/wp2/app_073.bin" "$WORK/match.json" "$WORK/srcmap.json" > "$WORK/srcmap.log"
$PY "$HERE/scripts/export_tables.py" "$WORK/match.json" "$HERE/data" "$WORK/srcmap.json"
echo "tables written to $HERE/data"
