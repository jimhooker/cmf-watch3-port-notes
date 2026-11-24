# CMF Watch 3 Pro: notes towards porting the Watch Pro 2 app loader

Analysis of stock Watch 3 Pro firmware `1.0.1.77` (board `jx402_08`) against Watch Pro 2 `1.0.0.73`, aimed at
what [`fmctools/cmf-watch-sdk`](https://github.com/fmctools/cmf-watch-sdk) would need to run its stub and loader
on the Watch 3 Pro. Snapshot of 2026-11-22, read against cmf-watch-sdk `528acf9` and cmf-watch-utils `7997d40`;
the seven addresses cmf-watch-sdk #22 added for storage inspection (point 9) and the app list in both views
(point 6) were worked out on 2026-11-23; the update path and the first install on a real watch
([On a real watch](#on-a-real-watch)) on 2026-11-24.

**One modified build has run on a physical watch**: the author's, stock `1.0.1.77`. Everything else is static
analysis or the emulator. Every claim is one of:

- **static**: read from the two public reference images (disassembly, tables, strings);
- **emulator**: observed in the cmf-watch-utils desktop emulator (`--profile wp3-stock`), Linux x64, runtime
  `emulator-v0.1.0-preview.10`;
- **real hardware**: one retail Watch 3 Pro on `1.0.1.77`, from Ubuntu 26.10 (BlueZ 5.87, bleak 3.0.2).

No firmware, vendor resources or device identifiers are in this repository. The scripts download the two public
reference images that cmf-watch-utils publishes.

## Headline results

| Question | Answer | Basis |
|---|---|---|
| Can the loader's 183 stock addresses be found? | 125 by automatic matching; of the 30 it missed outside the vibration tweak, 27 found by hand, 2 replaced by a different API, 1 absent | static |
| Are the found functions real? | 107 of 126 function addresses seen called with plausible arguments | emulator |
| Do the 37 "changed" functions behave the same? | 26 yes, 10 yes with a caveat, 1 is a string, not code | static |
| Are arc, bar, slider, roller, tileview present? | Yes, all five classes and their create functions | static + emulator |
| Did the property IDs move? | Yes: 0x00-0x23 unchanged, later ones shift (57 inserted, 4 removed) | static, 18 IDs cross-checked at call sites |
| Is the motor still PWM? | No. A haptic driver chip (AW86225 or SIH6164) behind an effect table | static + emulator |
| Can an entry be added to the stock app list? | Yes in List; yes in Grid while fewer than 30 stock entries are shown. Done first with stock calls from a debugger, then with a compiled stub (`patches/wp3-applist.patch`) | emulator |
| Are the app image or the update package signed? | No. The stock `app.bin` is a plain checksummed ACTH image (flags 0, no TLVs); the official package holds CRC32s and nothing else | static |
| Does a real Watch 3 Pro start an `app.bin` with changed code? | Yes. A stub appended to stock `app.bin` (an app-list entry and a set timer) installed over Bluetooth with the stock update protocol, and the watch restarted into it with its own face and settings | real hardware, one unit |

Cross-check against upstream: cmf-watch-sdk `516990f` (#24) derived Watch 3 Pro addresses independently for the
watch face guard (`fw/wp2-core/src/wfguard.rs`, `WP3`). The seven functions it shares with this table (`fs_open`,
`fs_close`, `fs_read`, `fs_write`, `fs_unlink`, `lv_timer_create`, `lv_timer_del`) have identical addresses, and
five more of its WP2 -> WP3 pairs match the matcher's own pairing; the matcher had no pairing for the other two.
The seven addresses #22 added (five fs functions, the FAT driver table, the partition-table pointer) are not in
`address-map.csv`, which was collected before it; they are at the end of `data/hunt-found.csv`.

## Things a port has to handle

1. **`lv_obj_t` grew by 4 bytes.** Everything from offset 0x14 up moves by 4: coords 0x14 -> 0x18, flags 0x24 -> 0x28,
   state 0x28 -> 0x2C, size 0x2C -> 0x30. `spec_attr` offsets seen so far are unchanged. Both builds are LVGL 8.x
   with the same event codes and style ids, but not the same point release, and the Watch 3 Pro build has the
   asserts compiled out. Label: text 0x2C -> 0x30, flags byte 0x5C -> 0x68 (the label grew 12). Image, simple image,
   roller: all fields +4. `jx_scroll_bar`: 0x58 -> 0x5C, 0x70 -> 0x78. Arc: value/min/max at 0x3A/0x3C/0x3E.
   Bar: cur/min/max/start at 0x30/0x34/0x38/0x3C.
2. **BLE hook.** The dispatcher is `0x100C2491`; its default branch reads the payload at `0x100C253A`
   (`bl 0x100C0EEC`). The frame pointer there is **r4**, not r5. Stock now handles opcodes up to **0x90E6**, including
   **0x90A2**, which is inside the stub's 0x90A0..0x90A7 block.
3. **Property IDs** (`data/property-ids.csv`): vibration level 0x24 -> 0x27, vibrate 0x26 -> 0x29, card settings
   0x2F -> 0x32 (length 98 -> 290), phone link 0x31 -> 0x34, media 0x4C..0x50 -> 0x53..0x57, GPS 0x62/0x63 -> 0x69/0x6A,
   return-to-face timeout 0x9C -> 0xA7. Bound is 0xD3, table at `0x10220DE4`.
4. **Vibration.** `PWM_PIN_SET_CYCLES` and `PWM_OFF` exist but are never called, even while the motor runs. Stock
   vibrates through `0x100DA77D (strength, effect)`, which calls the haptic device at `*0x380270AC` (driver table
   +0x18). Strength 0 stops. Strength table at `0x102217EC`: 0x7F, 0x50, 0. Effects are 12 entries of 0x44 bytes in
   ROM at `0x102217F8`, copied to RAM at `0x3802FF44` (`data/haptic-effects.csv`). Slot 11 is empty; a custom entry
   written there played as expected in the emulator.
5. **Time.** No drop-in `RTC_GET_TIME` / `TIME_ZONE`. The module keeps UTC seconds: `0x100B3CCD()` returns them,
   `0x100B3CED(ts)` returns the zone offset (DST-aware, 0 = now), `0x101D0CBF(ts, *rtc_time)` fills local time.
6. **App list** (`data/app-list.csv`). 30 entries now (table `0x10215788`, 12 bytes each; a target below 0x118 is
   a view id). Property 0x2F picks the style: 0 = List (descriptor `0x10215A58`), 1 = **Grid** (`0x10215938`), which
   was dead code on the Watch Pro 2 and is live here; the waterfall descriptor is no longer selectable.
   - Up to three entries are hidden by a flags byte at view data +0x290 (entry 11 ChatGPT, entry 9, entry 10), so
     the container can have fewer children than the count at +8. The stub's `child count == ROWS` check and its
     `0..ROWS` loop do not hold here.
   - List: layout slot `0x10215A64` holds `0x10047165`. Same row geometry; label style 0x200 -> 0x264, line height
     0x214 -> 0x274. The stock row now uses a plain LVGL label and `lv_label_set_string_dsc` (`0x1014C5D1`), not
     the vendor label. The stock fisheye (`0x10047009`) walks every child of the container, so an added row needs
     no fisheye callback of its own.
   - Grid: layout slot `0x10215944` holds `0x10046B6D`. Icons are 160 x 160 `simple_img` objects in a container at
     +0x1E4, with their pointers in a 30-slot array at +0x16C. `0x101C70EB(data)` places and zooms them, taking the
     count from the container's child count. An extra icon needs a free slot in that array, so it only fits while
     at least one stock entry is hidden.
   - The update handler (descriptor +0x10: `0x10047351` list, `0x10046D99` grid) rebuilds the screen by calling the
     stock layout directly when the flags change, which bypasses a patched layout slot. The generic view procedure
     calls +0x10 right after +0xC, so the update slots (`0x10215A68`, `0x10215948`) are the safer place to hook.
   - Emulator: `scripts/emu_applist_add.py` adds an entry in either view with stock calls from the UI thread. It
     shows, the stock code lays it out, and a tap opens its target.
   - Stub: `patches/wp3-applist.patch` (against cmf-watch-sdk `516990f`) adds this to `fw/wp3-stub` as two update
     hooks: header version 2, two rodata slots in `firmware.py`, 2,980 bytes in all. Booted in the emulator, an
     "Apps" entry with its own icon shows in both views and a tap runs the stub's callback (a 700 ms buzz as a
     placeholder, seen in the motor log). When the stock update rebuilds the screen the entry goes (29 -> 28
     children) and the hook puts it back. Not ported: the low-memory check the Watch Pro 2 stub makes before it
     allocates the icon.
7. **Widget cards.** The registry at `0x1021BEA0` has 24 dense slots (ids 0..23, bound `cmp r0, #0x17` at
   `0x1009498C`). There is no free slot to borrow.
8. **Smaller ones.** Heap: base `0x380E91C0`, size literal `0x636B00` in three slots (`0x1019C654`, `0x1019C700`,
   `0x1019C76C`). View table `0x1000050C`..`0x1000136C`, bounds literals at `0x101A1304/08` and `0x101A3194/98`.
   Wake-lock ids go up to 0x150 (was 0x124). `FONT_32M` is `/NAND:B/font32M.font` (volume B). `LV_ARC_GET_VALUE` was
   dropped by the linker: read the i16 at obj+0x3A. `ENCRYPT`/`DECRYPT` now take a mutex. GPS info block is
   `0x38020C68`, 0xA8 bytes, latitude at +0x68; `GPS_STATE` was not found (the GPS service was rewritten).
9. **Storage inspection (#22).** `FS_STAT` `0x10117039`, `FS_STATVFS` `0x101DDEB7`, `FS_OPENDIR` `0x10116FE1`,
   `FS_READDIR` `0x10117081`, `FS_CLOSEDIR` `0x10116D71`, FAT driver table `0x1022F18C`, partition-table pointer
   `0x3802BB04`. **`FS_READDIR` writes 4 more bytes than on the Watch Pro 2**: a u32 FAT date and time at
   entry+0x108, so the loader's 264-byte entry (`[0u32; 66]`) is too small here. `FS_STAT` still stops at 0x108.
   The driver table has one entry inserted at +0x34, so unlink, rename, mkdir, stat and statvfs sit 4 higher
   (stat +0x44, statvfs +0x48). Emulator: stock lists `/NAND:/` at boot through the three directory functions;
   stat and statvfs, called from the UI thread, returned a real file's name and size and a sane capacity; the
   `/NAND:` mount struct holds the driver table at +0x1C; the partition table passes the loader's checks (ACPT,
   size 744, entry size 24, CRC).

## On a real watch

Unofficial and at your own risk. One way this can end, an image the boot chain refuses to start, has no known
way back short of opening the watch. It did not happen here, but one unit does not rule it out for other builds.

**What was installed.** `patches/wp3-setlight.patch` (against cmf-watch-sdk `516990f`) extends `fw/wp3-stub`
with the app-list hook and a stand-up set timer ("Set Light": presets, one buzz to wrap up, three to get off,
then counting over time). It was built with `scripts/wp3_stub_build.sh SDK STOCK_APP OUT lazy`. `lazy` leaves
upstream's watch-face guard unpatched, so the only stock bytes that change are the size and checksum fields and
the two app-list update slots (`0x10215948`, `0x10215A68`). No stub code can run before the app list is opened,
and in the emulator no stub function is entered during boot. A crash forced at the hook's entry gave one watchdog
restart and a normal boot to the clock face. The stub is 4,840 bytes, appended at `0x102BD280`.

**The package.** `scripts/wp3_ota_build.py` takes the official 1.0.1.77 package and swaps `app.bin` inside
`TEMP.bin`, updating only the sizes and CRC32s that cover it. No `<version>` field and no version code changes.
Given the stock `app.bin` it reproduces the official package byte for byte.

**The transfer.** Pairing with cmf-watch-utils' `tools/cmf_watch.py pair` worked unchanged. The update used its
`tools/ota_client.py` through `scripts/wp3_ota_client.py`, with `--version 0100014d` (the watch's own version;
the client's default is a Watch Pro 2 value) and `--pipeline 1`. The watch pulled about 1.95 MB of the 45 MB
package (`TEMP.bin` and `sdfs_k.bin`) in about 30 s, answered `0xA041 01` and restarted. It came back on its own
watch face with its settings, and the new entry opened the timer. Buzz timing and a set with the screen off
behaved as designed. The Nothing X app paired again afterwards.

**Every notification arrives twice.** On the Linux machine used, every notification from the watch came twice, 1-4 ms
apart: the pairing frames, the AT replies and every `0xA042` data request. The upstream client answers both
copies. The watch then receives each range twice, logs CRC errors (reproduced in the emulator), asks again about
1.5 s later and finally rejects the staged copy with `0xA041 00`. Two attempts failed this way, one with the
default `--pipeline 4` and one with `--pipeline 1`. `scripts/wp3_ota_client.py` drops a notification identical
to the previous one within 0.2 s; with it 522 of 1,044 notifications were dropped and the transfer went through
with no repeats. Whether other platforms double the notifications was not checked.

**A rejected update leaves the watch on its update screen.** It shows a QR code and "please connect to the app to
upgrade again", and stays there across restarts, because the update-in-progress flag (`OTA_UPG_FLAG`) is not
cleared. Bluetooth, the AT shell and the update service keep working there, and the next good transfer clears it.

**Flicker when drawing over a stock screen.** The display path keeps two full-screen RGB565 buffers
(`0x3C5E1A34` and `0x3C64BB34`, 0x6A088 bytes each) and keeps re-sending the whole round screen from them in turn.
The timer is a panel laid over the app list, and with a plain `lv_label_set_text` once a second the seconds
digit flickered between the old value and the new digit drawn over the old one. Invalidating the whole panel
every 10 ms for 20 passes after each change (`OBJ_INVALIDATE` `0x101E52A9`) cured it on the watch. A port that
draws on top of stock screens will probably need the same. The emulator draws only into the first buffer, so it
cannot show this.

**Rehearsing in the emulator.** cmf-watch-utils' virtual stock update needs a few workarounds for this model:
- `emu pair-fixture` refuses to save when the guest ran with `--charger-connected`, because the runtime patches
  two app spots that `restore_wp3_runtime_patches` does not revert (+0x127EAC, +0x12C0C4).
  `scripts/emu_pair_capture.py` keeps the raw capture so they can be put back.
- `emu ota` takes only a package whose outer container holds `TEMP.bin` alone: `scripts/wp3_ota_temponly.py`.
- The update-progress screen writes display-engine register `0x4006C020`, which the machine does not model, so a
  full-size transfer halts about 6% in. `scripts/emu_exploratory.py` runs `emu` with the machine's exploratory
  mode, which logs and skips that write.
- `emu recover --qmp-port` is Watch Pro 2 only: `scripts/emu_capture_ota_reset.py` saves the NOR at the update
  reboot for `emu recover --nor ... --pending-temp ...`.

With these, the virtual watch took the whole package from the stock client, checked it ("verify pass"), rebooted,
and the modelled install booted like stock. That covers transfer and stock validation, not the real bootloader.
`data/boot-recovery.csv` collects this and the recovery study behind it: image header, the public Actions SDK
bootloader and installer source, safe mode, the crash path, and what other owners report from real hardware.

## Files

| Path | What |
|---|---|
| `data/address-map.csv` | The automatic pass over the 185 addresses hard-coded in the SDK. `derived` rows are guesses and mostly wrong: see next file |
| `data/hunt-found.csv` | Hand-found addresses and corrected guesses. **Overrides `address-map.csv`** where they differ |
| `data/changed-functions-review.csv` | Verdict per changed function, with the struct offsets seen |
| `data/property-ids.csv` | Full alignment of the two ux2sys tables, with evidence per row |
| `data/haptic-effects.csv` | The 12 haptic effects: table contents and the pattern observed in the emulator |
| `data/app-list.csv` | The stock app list in List and Grid view: tables, handlers, view-data offsets, Watch Pro 2 value beside each |
| `data/emu-hit-summary.csv` | Which function addresses were seen called, in an idle boot and in a scripted UI tour |
| `data/emu-hits*.csv`, `data/hunt-emu-hits.csv` | First calls recorded per function: r0-r3, lr, string arguments |
| `data/layers.csv`, `data/summary.json` | How much of each firmware layer carried over |
| `scripts/run_all.sh` | Rebuilds `address-map.csv`, `functions.csv`, `layers.csv` from the public images in about 20 s |
| `scripts/match.py` | The matcher: masked signatures, call-graph propagation, fuzzy alignment |
| `scripts/fn_pair.py`, `scripts/callseq.py` | Whole-function side-by-side dumps with named calls; call-sequence and offset comparison |
| `scripts/hunt/` | Helpers for finding things by hand: class tables, region sweep, property alignment and its check |
| `scripts/emu_hits.sh`, `scripts/emu_tour.py` | Breakpoint probe on every known address; scripted crown/touch tour with screenshots |
| `scripts/emu_call.py` | Calls stock functions from the UI thread in the emulator (up to six arguments; later calls can use what earlier ones returned and follow pointers), with input, screenshots and memory writes between calls; records the motor log and memory dumps |
| `scripts/emu_snap.py` | Saves memory when chosen functions are entered or return, with scripted input and screenshots |
| `scripts/emu_applist_add.py` | Adds one entry to the stock app list in the emulator, List or Grid, with stock calls only |
| `patches/wp3-applist.patch` | The app-list hook for `fw/wp3-stub`, as a diff against cmf-watch-sdk `516990f` (MIT, like the code it changes) |
| `patches/wp3-setlight.patch` | The app-list hook plus the Set Light timer, the `guard=False` option of `patch_wp3` and the redraw fix: the build that ran on a real watch. Same base and licence |
| `scripts/wp3_stub_build.sh` | Builds the Watch 3 Pro stub and patches it onto a stock app.bin with cargo, objcopy and python3 only; `lazy` leaves the watch-face guard out |
| `scripts/emu_launch.py` | How the emu scripts start the emulator; `EMU_APP=app.bin` boots a modified image, `EMU_TRACE_MMIO=1` records device accesses |
| `scripts/emu_snap.py` | `--attach boot` attaches the debugger from the first instruction, to watch the boot path |
| `data/boot-recovery.csv` | What the watch does when an update or a patched image goes wrong, with sources: static, SDK source, emulator, real hardware |
| `scripts/wp3_ota_build.py` | Builds an update package from the official one with only `app.bin` swapped, then checks the result against it |
| `scripts/wp3_ota_client.py` | cmf-watch-utils' stock update client with the repeated-notification filter (`physical` or `emu`) |
| `scripts/wp3_readonly.py` | Four fixed read-only AT queries over Bluetooth, no pairing; takes no command from the caller |
| `scripts/wp3_ota_temponly.py`, `scripts/emu_pair_capture.py`, `scripts/emu_capture_ota_reset.py`, `scripts/emu_exploratory.py` | The emulator rehearsal workarounds described above |

`data/functions.csv` (all 8,869 Watch Pro 2 functions and their twins) is not included because its first two
columns come straight from cmf-watch-utils' `function_map.tsv`; `scripts/run_all.sh` regenerates it, and
`fn_pair.py` and `scripts/hunt/` need it.

## Reproducing

```sh
# checkouts side by side, no Git LFS needed
git clone https://github.com/fmctools/cmf-watch-sdk
git clone https://github.com/fmctools/cmf-watch-utils
python3 -m venv .venv && .venv/bin/pip install capstone numpy
PYTHON=.venv/bin/python scripts/run_all.sh cmf-watch-sdk cmf-watch-utils work
```

The emulator scripts expect `work/runtime/` (QEMU and `compat.bin` from the emulator release, plus
`nand_id_all.bin`), `work/fixtures-wp3/` from `emu prepare-fixtures --profile wp3-stock`, and an Arm-capable gdb.
Stock boots twice on first power-on, so runs need `--allow-reboot --watch-face-preview`.

A layout fact that makes hand-hunting quick: functions with literal pools are linked first
(`0x1004xxxx`-`0x101Bxxxx`), functions without come after (`0x101Cxxxx`-`0x101Exxxx`), and each group keeps
source-file order. The Watch 3 Pro lost its LVGL asserts, so many LVGL functions moved to the second group.

## Limits

- Static matching and emulator observation only. "Called with plausible arguments" is weaker than "behaves the same".
- Property alignment compares which handler sits at which number, not the values a property carries.
- The 17 addresses of the optional "Weak" vibration tweak were not attempted; the motor it patches is not used here.
- The emulator models the SIH6164 path. Which haptic chip real units carry, and how effects feel, is untested.
- Real hardware means one unit and one build. The watch's own second-stage bootloader was never read out, so what
  it does with an image it refuses, and with power loss during the install, is known only from the public Actions
  SDK source, which ends in a loop with no Bluetooth.
- The Watch 3 Pro partition sizes were not measured. The emulator and `check_acth` reuse the Watch Pro 2 app
  partition (`0x34B000`); the 1.0.1.77 app plus this stub (`0x2BE568` bytes) leave 576,152 bytes of it free.
- The app-list patch alone (`wp3-applist.patch`) only ran in the emulator; `wp3-setlight.patch` includes it and ran
  on the watch.

## Licence

MIT, see `LICENSE`. The scripts read cmf-watch-utils (AGPL-3.0) data as an input or run its tools, and copy none
of its code. `wp3_ota_client.py`, `emu_pair_capture.py`, `emu_capture_ota_reset.py` and `emu_exploratory.py`
import cmf-watch-utils modules when they run; that running combination is covered by AGPL-3.0. No firmware,
update package or patched image is published here: build your own from the official download.
