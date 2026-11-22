#!/usr/bin/env python3
"""Turn match.py's JSON into the CSV tables in data/.

usage: export_tables.py MATCH_JSON OUT_DIR [SRCMAP_JSON]

Writes:
  address-map.csv   every firmware address the cmf-watch-sdk loader depends on: Watch Pro 2 -> Watch 3 Pro
  functions.csv     every Watch Pro 2 function: class and Watch 3 Pro twin where one was found
  layers.csv        firmware layers (address ranges on the Watch Pro 2) and how much of each carried over
  summary.json      headline numbers
"""
import collections
import csv
import json
import sys
from pathlib import Path

# Layer boundaries on Watch Pro 2 1.0.0.73, read off the source paths baked into the firmware (srcmap.py):
# each library occupies one contiguous block of addresses. Approximate at the edges.
LAYERS = [
    ("Watch app (application/bt_watch)", [(0x100586A4, 0x100EDFEC)], "screens, JX widgets, watch-face manager, ux2sys settings"),
    ("Display and UI service (framework/display)", [(0x101822C0, 0x10199144)], "view stack/cache/manager, input, surfaces, ui_mem"),
    ("Graphics library (thirdparty/lib/gui/lvgl)", [(0x101255E0, 0x10145D84)], "LVGL core/draw/widgets/extra + Actions GPU and VGLite porting"),
    ("System services (framework/base, system, audio, ota)", [(0x10145D84, 0x1015E4A4)], "app/service manager, streams, logging, audio, OTA"),
    ("Bluetooth stack (framework/bluetooth)", [(0x1015E4A4, 0x101822C0)], "bt_manager + bt_stack (BR/EDR and LE)"),
    ("Zephyr OS and drivers (zephyr/...)", [(0x100EDFEC, 0x101255E0), (0x10199144, 0x1019C400)], "lib/os, soc, subsys, drivers, HAL, arch, kernel"),
    ("C and maths libraries (newlib and others)", [(0x10040000, 0x100586A4), (0x101A8000, 0x101B0000), (0x101B8000, 0x10300000)], "newlib and unnamed library code"),
    ("Unlabelled code", [(0x10000000, 0x10040000), (0x1019C400, 0x101A8000), (0x101B0000, 0x101B8000)], "no path strings; almost none matched"),
]
K = {"identical": 0, "same-shape": 1, "similar": 1, "rewritten": 1, "no counterpart found": 2}


def group(r):
    n = r["name"] or ""
    if r["file"].endswith("firmware.py") and 40 <= r["line"] <= 70:
        return "vibration tweak (optional extra)"
    if n.startswith(("LV_", "LVGL_", "OBJ_", "FONT_")) or n == "EVENT_SEND":
        return "graphics library"
    if n.startswith(("VIEW_", "VLABEL_", "VIMG_", "SIMPLE_IMG", "JX_", "SCENE_", "SPORT1_", "CARDS_", "RETURN_")) or n in (
            "APPLIST_LAYOUT", "STOCK_LAYOUT", "WGT_REG", "POPUP_FLAGS"):
        return "screens and widgets"
    if n.startswith(("UX2SYS_", "KV_", "RTC_", "WAKE_", "POWER_", "PWM_", "HR_", "GPS_", "STREAM_")) or n in (
            "TIME_ZONE", "STOCK_BLE_READ", "BLE_CALL", "READ_PAYLOAD", "SEND", "ENCRYPT", "DECRYPT", "SESSION_KEY",
            "AUTHKEY", "WEWEAR_CTX"):
        return "watch services"
    if n.startswith(("FS_", "OS_", "K_", "SYS_", "UI_MEM_", "PSRAM_", "HEAP")) or n in (
            "STOCK_HEAP_INIT", "stock_heap_init", "BOOT_CALL", "STUB_RAM", "APP_VBASE"):
        return "files, memory and system"
    return "other"


def confidence(r):
    st = r["status"]
    if st in ("unresolved", "conflict") or r["kind"] == "patch-area":
        return ""
    if st == "derived":
        return "low"
    src = r.get("source", "")
    if r["kind"] == "function":
        if r.get("body") == "identical" or r.get("votes", 0) >= 4:
            return "high"
        return "medium"
    if src in ("aligned", "data-ref"):
        return "high"
    return "medium"


def main():
    R = json.load(open(sys.argv[1]))
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    src = json.load(open(sys.argv[3]))["attr"] if len(sys.argv) > 3 else {}

    rows = []
    for r in R["rom"] + R["ram"]:
        status = "own-placement" if r["kind"] == "patch-area" else r["status"]
        review = ""
        if status == "located" and r["kind"] == "function" and r.get("body") != "identical":
            review = "code differs: check behaviour, arguments and struct offsets"
        elif status == "derived":
            review = "address guessed from a nearby mapped base plus the same offset"
        elif status == "located" and r["kind"] != "function":
            review = "address found; contents not compared"
        rows.append({
            "name": r["name"], "group": group(r), "kind": r["kind"],
            "wp2_addr": f"{r['addr']:#010x}", "wp3_addr": f"{r['b']:#010x}" if "b" in r else "",
            "status": status, "how": r.get("source", ""), "address_confidence": confidence(r),
            "body": r.get("body", ""), "similarity": f"{r['ratio']:.2f}" if "ratio" in r else "",
            "votes": r.get("votes", ""), "review_note": review,
            "sdk_file": r["file"], "sdk_line": r["line"],
        })
    with open(out / "address-map.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    anchors = {int(k, 16): v for k, v in R["anchors"].items()}
    with open(out / "functions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["wp2_entry", "size", "class", "wp3_entry", "how", "source_file"])
        for e, s, c in R["fmap"]:
            a = anchors.get(e)
            w.writerow([f"{e:#010x}", s, "none" if c == "no counterpart found" else c,
                        a[0] if a else "", a[1] if a else "", src.get(hex(e), "")])

    tot = sum(s for _, s, _ in R["fmap"])
    with open(out / "layers.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["layer", "wp2_ranges", "functions", "code_kb", "share_of_code_pct", "same_pct", "changed_pct",
                    "none_pct", "contents"])
        for name, ranges, what in LAYERS:
            b, n = [0, 0, 0], 0
            for e, s, c in R["fmap"]:
                if any(lo <= e < hi for lo, hi in ranges):
                    b[K[c]] += s
                    n += 1
            t = sum(b) or 1
            w.writerow([name, " ".join(f"{lo:#x}-{hi:#x}" for lo, hi in ranges), n, round(t / 1024, 1),
                        round(100 * t / tot, 1), round(100 * b[0] / t, 1), round(100 * b[1] / t, 1),
                        round(100 * b[2] / t, 1), what])

    matchable = [r for r in rows if r["status"] != "own-placement"]
    found = [r for r in matchable if r["status"] in ("located", "derived")]
    fn = [r for r in rows if r["kind"] == "function"]
    by_bytes = [0, 0, 0]
    for e, s, c in R["fmap"]:
        by_bytes[K[c]] += s
    summary = {
        "loader_addresses_total": len(rows),
        "matchable": len(matchable),
        "found": len(found),
        "found_pct": round(100 * len(found) / len(matchable), 1),
        "of_which_derived_guesses": sum(1 for r in found if r["status"] == "derived"),
        "functions": len(fn),
        "function_bodies": dict(collections.Counter(r["body"] or "not found" for r in fn)),
        "by_group": {g: dict(collections.Counter(r["status"] for r in rows if r["group"] == g))
                     for g in sorted({r["group"] for r in rows})},
        "wp2_functions": len(R["fmap"]),
        "wp2_functions_by_class": R["summary"]["all_functions_body"],
        "wp2_code_bytes_pct": {"same": round(100 * by_bytes[0] / tot, 1), "changed": round(100 * by_bytes[1] / tot, 1),
                               "none": round(100 * by_bytes[2] / tot, 1)},
        "self_check": R["summary"]["check"],
    }
    json.dump(summary, open(out / "summary.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
